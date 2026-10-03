#include "chain.h"
extern volatile int fd_sink;
#define F(N,NEXT) __attribute__((noinline)) void fd_chain_d##N(int n){fd_sink+=N;if(n>N)fd_chain_d##NEXT(n);}
F(17,18) F(18,19) F(19,20) F(20,21) F(21,22) F(22,23) F(23,24) F(24,25)
F(25,26) F(26,27) F(27,28) F(28,29) F(29,30) F(30,31) F(31,32) F(32,33)
F(33,34) F(34,35) F(35,36) F(36,37) F(37,38) F(38,39) F(39,40) F(40,41)
F(41,42) F(42,43) F(43,44) F(44,45) F(45,46) F(46,47) F(47,48) F(48,49)
F(49,50) F(50,51) F(51,52) F(52,53) F(53,54) F(54,55) F(55,56) F(56,57)
F(57,58) F(58,59) F(59,60) F(60,61) F(61,62) F(62,63) F(63,64)
__attribute__((noinline)) void fd_chain_d64(int n){fd_sink+=n;}
