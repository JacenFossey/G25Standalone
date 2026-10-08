#pragma once

// Force-load every header used by driver.cpp before masking the contextual
// keyword below. MSVC's standard library intentionally rejects an `override`
// macro while its own headers are being parsed.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <dinput.h>
#include <dinputd.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <limits>
#include <mutex>
#include <new>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

// dinputd.h's COM interfaces predate C++11 and do not declare virtual
// destructors. driver.cpp uses `override` consistently; after all dependencies
// are parsed, erase the contextual specifier for this translation unit only.
#define override
