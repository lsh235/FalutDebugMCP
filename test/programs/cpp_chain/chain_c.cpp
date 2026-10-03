#include "chain.h"
namespace fd_cpp { extern volatile int sink; }
#define F(N,NEXT) __attribute__((noinline)) void fd_cpp_c##N(int n){fd_cpp::sink+=N;if(n>N)fd_cpp_c##NEXT(n);}
F(9,10) F(10,11) F(11,12) F(12,13) F(13,14) F(14,15) F(15,16) F(16,17)
F(17,18) F(18,19) F(19,20) F(20,21) F(21,22) F(22,23) F(23,24) F(24,25)
F(25,26) F(26,27) F(27,28) F(28,29) F(29,30) F(30,31) F(31,32)
__attribute__((noinline)) void fd_cpp_c32(int n){fd_cpp::sink+=n;}
