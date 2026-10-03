#include "chain.h"
namespace fd_cpp { extern volatile int sink; }
__attribute__((noinline)) void fd_cpp_b5(int n){fd_cpp::sink+=5;if(n>5)fd_cpp_b6(n);}
__attribute__((noinline)) void fd_cpp_b6(int n){fd_cpp::sink+=6;if(n>6)fd_cpp_b7(n);}
__attribute__((noinline)) void fd_cpp_b7(int n){fd_cpp::sink+=7;if(n>7)fd_cpp_b8(n);}
__attribute__((noinline)) void fd_cpp_b8(int n){fd_cpp::sink+=8;if(n>8)fd_cpp_c9(n);}
