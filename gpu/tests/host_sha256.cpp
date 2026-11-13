// CPU-only algorithm cross-check. This is never evidence of CUDA execution.
#include "../cuda/kernels/sha256.h"
extern "C" void host_sha256(const uint8_t* p,unsigned n,uint8_t* out){sha256(p,n,out);}
extern "C" void host_sha256d(const uint8_t* p,uint32_t n,uint8_t* out){sha256d(p,n,out);}
extern "C" bool host_meets(const uint8_t* p,const uint8_t* t){return meets_target(p,t);}
