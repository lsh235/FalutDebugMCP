#include "complex.h"
__attribute__((noinline)) int fd_complex_recurse(int depth){return depth<=0?1:depth+fd_complex_recurse(depth-1);}
__attribute__((noinline)) int fd_complex_branch(int value){return (value&1)?fd_complex_recurse(3):fd_complex_recurse(2);}
