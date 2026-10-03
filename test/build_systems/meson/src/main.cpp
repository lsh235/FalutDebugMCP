#include <cstdio>

extern "C" int helper_value(void);
extern "C" int generated_value(void);

int main() {
    std::printf("%d\n", helper_value() + generated_value());
    return 0;
}
