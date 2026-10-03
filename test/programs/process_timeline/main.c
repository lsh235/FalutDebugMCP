#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static long long now_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (long long)t.tv_sec*1000000000LL+t.tv_nsec;}
int main(int argc,char **argv){if(argc<3)return 2;const char *out=argv[1],*trace=argv[2];int p[2];if(pipe(p))return 3;pid_t child=fork();if(child<0)return 4;if(!child){close(p[0]);dprintf(p[1],"send child %s %lld\n",trace,now_ns());close(p[1]);_exit(0);}close(p[1]);FILE *f=fopen(out,"w");if(!f)return 5;char line[256];if(!fgets(line,sizeof(line),fdopen(p[0],"r")))return 6;fprintf(f,"%s",line);fprintf(f,"recv parent %s %lld\n",trace,now_ns());fclose(f);int st;waitpid(child,&st,0);return WIFEXITED(st)?WEXITSTATUS(st):7;}
