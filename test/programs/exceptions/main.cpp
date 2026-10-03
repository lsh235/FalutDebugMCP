#include <stdexcept>
#include <cstdlib>
static volatile int sink;
__attribute__((noinline)) static void thrower(int n){if(n)throw std::runtime_error("fixture");sink++;}
__attribute__((noinline)) static int catcher(int n){try{thrower(n);return 0;}catch(const std::runtime_error&){sink+=3;return 1;}}
int main(int argc,char **argv){return catcher(argc>1?std::atoi(argv[1]):1)==1?0:2;}
