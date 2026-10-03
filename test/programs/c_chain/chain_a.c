#include "chain.h"
extern volatile int fd_sink;
__attribute__((noinline)) void fd_chain_a1(int n){fd_sink+=1;if(n>1)fd_chain_a2(n);}
__attribute__((noinline)) void fd_chain_a2(int n){fd_sink+=2;if(n>2)fd_chain_a3(n);}
__attribute__((noinline)) void fd_chain_a3(int n){fd_sink+=3;if(n>3)fd_chain_a4(n);}
__attribute__((noinline)) void fd_chain_a4(int n){fd_sink+=4;if(n>4)fd_chain_b5(n);}
