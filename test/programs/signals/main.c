#define _GNU_SOURCE
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <sys/stat.h>
__attribute__((noinline)) static void fd_segv(void){size_t p=(size_t)sysconf(_SC_PAGESIZE);if(!p)_exit(90);void *x=mmap(0,p,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);if(x==MAP_FAILED)_exit(90);volatile char *q=(volatile char*)x;(void)*q;}
__attribute__((noinline)) static void fd_bus(void){char name[]="/tmp/fd-bus-XXXXXX";int f=mkstemp(name);if(f<0)_exit(90);if(ftruncate(f,1)<0)_exit(90);char *m=mmap(0,8192,PROT_READ,MAP_PRIVATE,f,0);if(m==MAP_FAILED)_exit(90);unlink(name);volatile char x=m[4096];(void)x;}
#if defined(__x86_64__)
__attribute__((noinline)) static void fd_ill(void){__asm__ volatile("ud2");}
__attribute__((noinline)) static void fd_fpe(void){volatile unsigned a=1,b=0;__asm__ volatile("divl %1":"=a"(a):"r"(b),"a"(a),"d"(0));}
#else
__attribute__((noinline)) static void fd_ill(void){raise(SIGILL);}
__attribute__((noinline)) static void fd_fpe(void){raise(SIGFPE);}
#endif
int main(int argc,char **argv){int s=argc>1?atoi(argv[1]):6;switch(s){case 11:fd_segv();break;case 7:fd_bus();break;case 4:fd_ill();break;case 8:fd_fpe();break;case 6:abort();break;default:return 2;}return 0;}
