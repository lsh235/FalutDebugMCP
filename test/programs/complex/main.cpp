#include "complex.h"
#include <cstring>
#include <iostream>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>
struct Worker{int fd;int id;};
static void *worker(void *opaque){Worker*w=(Worker*)opaque;char c=(char)fd_complex_shared(fd_complex_branch(w->id));(void)!write(w->fd,&c,1);return nullptr;}
static int child_stage(int fd){char c=0;if(read(fd,&c,1)!=1)_exit(41);return c==8?0:42;}
int main(int argc,char**argv){bool fault=argc>1&&!std::strcmp(argv[1],"fault");int ipc[2],pfd[2];if(socketpair(AF_UNIX,SOCK_STREAM,0,ipc)||pipe(pfd))return 10;pid_t child=fork();if(child<0)return 12;if(!child){close(pfd[1]);int r=child_stage(pfd[0]);_exit(r);}close(pfd[0]);char done=8;if(write(pfd[1],&done,1)!=1)return 14;close(pfd[1]);pthread_t ts[8];Worker ws[8];for(int i=0;i<8;i++){ws[i]={ipc[1],i};if(pthread_create(&ts[i],0,worker,&ws[i]))return 13;}int got=0;for(int i=0;i<8;i++){char c;if(read(ipc[0],&c,1)==1)got++;}for(auto&t:ts)pthread_join(t,0);close(ipc[0]);close(ipc[1]);int st;waitpid(child,&st,0);int cr=WIFEXITED(st)?WEXITSTATUS(st):-1;std::cout<<"complex marker threads=8 ipc="<<got<<" child="<<cr<<"\n";if(got!=8||cr!=0)return 15;if(fault)__builtin_trap();return 0;}
