#include <cstring>

namespace consumer {

static __attribute__((noinline)) int cpp_leaf(int value) {
    return value + 11;
}

static __attribute__((noinline)) int cpp_middle(int value) {
    return cpp_leaf(value * 2);
}

static __attribute__((noinline)) int cpp_fault() {
    volatile int *invalid = nullptr;
    *invalid = 11;
    return 0;
}

static __attribute__((noinline)) int cpp_entry(bool fault) {
    const int value = cpp_middle(3);
    return fault ? cpp_fault() : value;
}

}  // namespace consumer

int main(int argc, char **argv) {
    const bool fault = argc > 1 && std::strcmp(argv[1], "--fault") == 0;
    const int value = consumer::cpp_entry(fault);
    return value == 17 ? 0 : 3;
}
