#include "chain.h"
volatile int fd_sink;
__attribute__((noinline)) void fd_chain_c9(int n){fd_sink+=9;if(n>9)fd_chain_c10(n);}
__attribute__((noinline)) void fd_chain_c10(int n){fd_sink+=10;if(n>10)fd_chain_c11(n);}
__attribute__((noinline)) void fd_chain_c11(int n){fd_sink+=11;if(n>11)fd_chain_c12(n);}
__attribute__((noinline)) void fd_chain_c12(int n){fd_sink+=12;if(n>12)fd_chain_c13(n);}
__attribute__((noinline)) void fd_chain_c13(int n){fd_sink+=13;if(n>13)fd_chain_c14(n);}
__attribute__((noinline)) void fd_chain_c14(int n){fd_sink+=14;if(n>14)fd_chain_c15(n);}
__attribute__((noinline)) void fd_chain_c15(int n){fd_sink+=15;if(n>15)fd_chain_c16(n);}
__attribute__((noinline)) void fd_chain_c16(int n){fd_sink+=16;if(n>16)fd_chain_d17(n);}
