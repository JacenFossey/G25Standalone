#pragma once

// dinputd.h's legacy COM interfaces predate C++11 and do not declare virtual
// destructors. driver.cpp uses `override` consistently on COM methods and its
// destructors; erase the contextual specifier at preprocessing time so MSVC
// accepts the historical interface definitions without changing dispatch.
//
// This header is force-included only for g25ff.dll.
#define override
