cmake_minimum_required(VERSION 3.24)
project(G25StandaloneFF VERSION 0.1.0 LANGUAGES CXX)

if(NOT WIN32)
    message(FATAL_ERROR "g25ff is a Windows DirectInput driver")
endif()

add_library(g25ff SHARED driver.cpp g25ff.def)
target_compile_features(g25ff PRIVATE cxx_std_20)
target_compile_definitions(g25ff PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_compile_options(g25ff PRIVATE /W4 /permissive- /EHsc)
target_link_libraries(g25ff PRIVATE ws2_32)
set_target_properties(g25ff PROPERTIES OUTPUT_NAME "g25ff")
