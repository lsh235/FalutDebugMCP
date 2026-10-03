#include "chain.h"
extern volatile int fd_sink;
__attribute__((noinline)) void fd_chain_b5(int n){fd_sink+=5;if(n>5)fd_chain_b6(n);}
__attribute__((noinline)) void fd_chain_b6(int n){fd_sink+=6;if(n>6)fd_chain_b7(n);}
__attribute__((noinline)) void fd_chain_b7(int n){fd_sink+=7;if(n>7)fd_chain_b8(n);}
__attribute__((noinline)) void fd_chain_b8(int n){fd_sink+=8;if(n>8)fd_chain_c9(n);}
