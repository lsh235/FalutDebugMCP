#include "chain.h"
#include <cstdlib>
int main(int argc,char **argv){int d=argc>1?std::atoi(argv[1]):8;if(d<1)d=1;if(d>32)d=32;fd_cpp_member_entry(d);fd_cpp_a1(d);return (argc>2)?__builtin_trap(),127:0;}
