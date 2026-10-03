#include "chain.h"
namespace fd_cpp { volatile int sink; }
class ChainMember { public: __attribute__((noinline)) void step(int n){fd_cpp::sink+=n;} __attribute__((noinline)) void step(const char *s){fd_cpp::sink+=(s&&*s)?1:0;} };
__attribute__((noinline)) void fd_cpp_member_entry(int n){ChainMember c;c.step(n);c.step("member-overload");}
__attribute__((noinline)) void fd_cpp_a1(int n){fd_cpp::sink+=1;if(n>1)fd_cpp_a2(n);}
__attribute__((noinline)) void fd_cpp_a2(int n){fd_cpp::sink+=2;if(n>2)fd_cpp_a3(n);}
__attribute__((noinline)) void fd_cpp_a3(int n){fd_cpp::sink+=3;if(n>3)fd_cpp_a4(n);}
__attribute__((noinline)) void fd_cpp_a4(int n){fd_cpp::sink+=4;if(n>4)fd_cpp_b5(n);}
