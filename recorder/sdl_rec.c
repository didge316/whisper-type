/* Lightweight SDL2 capture -> 16kHz mono 16-bit WAV.
   Runs until killed (SIGTERM/SIGINT) then writes a clean WAV.
   SDL 2.28+ API (SDL_OpenAudioDevice iscapture=1, SDL_DequeueAudio, CVT resample).
   Usage: sdl_rec <device-id> <seconds=0=infinite> <out.wav> */
#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <string.h>
#include <errno.h>

static volatile int stop = 0;
static void on_sig(int s){ (void)s; stop = 1; }

static void put32(unsigned char*h, unsigned long v){ h[0]=v;h[1]=v>>8;h[2]=v>>16;h[3]=v>>24; }

int main(int argc, char** argv){
    int dev_id = argc > 1 ? atoi(argv[1]) : 0;
    int secs   = argc > 2 ? atoi(argv[2]) : 0;
    const char* out = argc > 3 ? argv[3] : "/tmp/sdl_rec.wav";

    signal(SIGTERM, on_sig); signal(SIGINT, on_sig);

    if(SDL_Init(SDL_INIT_AUDIO) != 0){ fprintf(stderr,"SDL_Init: %s\n", SDL_GetError()); return 2; }

    const char* dname = SDL_GetAudioDeviceName(dev_id, 1);
    if(!dname){ fprintf(stderr,"no capture device %d\n", dev_id); SDL_Quit(); return 3; }

    const int SR = 16000, CH = 1, BPS = 2;
    SDL_AudioSpec want, have; SDL_AudioCVT cvt;
    memset(&want,0,sizeof want); memset(&cvt,0,sizeof cvt);
    want.freq = SR; want.format = AUDIO_S16SYS; want.channels = CH; want.samples = 1024;

    SDL_AudioDeviceID devid = SDL_OpenAudioDevice(dname, 1, &want, &have, 0);
    if(devid == 0){ fprintf(stderr,"OpenAudioDevice(capture): %s\n", SDL_GetError()); SDL_Quit(); return 3; }
    printf("capture dev %d (%s) -> in=%dHz/%dch out=%dHz/%dch\n",
           dev_id, dname, have.freq, have.channels, want.freq, want.channels);

    int bc = SDL_BuildAudioCVT(&cvt, have.format, have.channels, have.freq,
                               want.format, want.channels, want.freq);
    if(bc < 0){ fprintf(stderr,"BuildAudioCVT failed: %s\n", SDL_GetError());
                SDL_CloseAudioDevice(devid); SDL_Quit(); return 5; }
    /* bc==0 means source already matches dst; SDL_ConvertAudio still works */
    size_t in_cap  = (size_t)have.samples * have.channels * BPS;
    size_t out_cap = in_cap * cvt.len_mult + 15;
    unsigned char* inbuf  = malloc(in_cap);
    unsigned char* outbuf = malloc(out_cap);
    if(!inbuf || !outbuf){ fprintf(stderr,"oom\n"); return 6; }
    cvt.buf = outbuf;

    SDL_PauseAudioDevice(devid, 0); /* start capture */

    FILE* f = fopen(out, "wb");
    if(!f){ fprintf(stderr,"fopen %s: %s\n", out, strerror(errno)); return 4; }
    unsigned char hdr[44]; memset(hdr,0,sizeof hdr);
    memcpy(hdr,"RIFF",4); memcpy(hdr+8,"WAVE",4); memcpy(hdr+12,"fmt ",4);
    hdr[16]=16; hdr[20]=1; hdr[21]=0; hdr[22]=(unsigned char)CH; hdr[23]=0;
    put32(hdr+24,SR); put32(hdr+28,(unsigned long)CH*BPS*SR);
    hdr[30]=0;
    hdr[32]=(unsigned char)(CH*BPS); hdr[33]=0; /* blockAlign */
    hdr[34]=(unsigned char)(8*BPS); hdr[35]=0;  /* bitsPerSample */
    memcpy(hdr+36,"data",4);
    fwrite(hdr,1,44,f);

    unsigned long samples = 0;
    while(!stop){
        size_t n = SDL_DequeueAudio(devid, inbuf, in_cap);
        if(n > 0){
            cvt.len = (int)n;
            memcpy(cvt.buf, inbuf, n);
            SDL_ConvertAudio(&cvt);
            fwrite(cvt.buf, 1, cvt.len_cvt, f);
            samples += cvt.len_cvt / (CH*BPS);
        }
        if(secs > 0 && samples >= (unsigned long)secs * SR) break;
    }
    fclose(f);

    FILE* h = fopen(out, "r+b");
    if(h){
        unsigned long total = 36 + samples*CH*BPS;
        fseek(h, 4, SEEK_SET);   put32(hdr+4, total);   fwrite(hdr+4,1,4,h);
        fseek(h, 40, SEEK_SET);  put32(hdr+40, samples*CH*BPS); fwrite(hdr+40,1,4,h);
        fclose(h);
    }
    free(inbuf); free(outbuf);
    SDL_CloseAudioDevice(devid); SDL_Quit();
    printf("wrote %s dur=%.2fs samples=%lu\n", out, (double)samples/(CH*SR), samples);
    return 0;
}
