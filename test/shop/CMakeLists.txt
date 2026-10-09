add_library(shop_boundary SHARED boundary.cc)
target_compile_features(shop_boundary PRIVATE cxx_std_17)
target_compile_options(shop_boundary PRIVATE -g -O0 -fno-omit-frame-pointer)
faultdebug_instrument(shop_boundary)
