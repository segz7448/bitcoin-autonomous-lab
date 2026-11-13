#include <cuda_runtime.h>
#include <stdint.h>
#define BAL_DEVICE __device__
#include "kernels/sha256.h"

__global__ void nonce_kernel(const uint8_t* h,uint64_t start,uint32_t count,
                            const uint8_t* target,uint8_t* hashes,uint8_t* flags) {
 uint64_t i=(uint64_t)blockIdx.x*blockDim.x+threadIdx.x;
 if(i>=count)return;
 sha256d(h,(uint32_t)(start+i),hashes+32*i);
 flags[i]=meets_target(hashes+32*i,target);
}
// Numeric CUDA status only. No device-name/property/identifier interfaces.
extern "C" int bal_batch(const uint8_t* header,uint64_t start,uint32_t count,
                         const uint8_t* target,unsigned threads,uint8_t* hashes,uint8_t* flags) {
 if(!count || !threads || start+count>0x100000000ULL)return -1;
 int max_threads=0,dim_x=0,grid_x=0;
 cudaError_t e=cudaDeviceGetAttribute(&max_threads,cudaDevAttrMaxThreadsPerBlock,0);
 if(e!=cudaSuccess)return (int)e;
 e=cudaDeviceGetAttribute(&dim_x,cudaDevAttrMaxBlockDimX,0);if(e!=cudaSuccess)return (int)e;
 e=cudaDeviceGetAttribute(&grid_x,cudaDevAttrMaxGridDimX,0);if(e!=cudaSuccess)return (int)e;
 uint64_t blocks=((uint64_t)count+threads-1)/threads;
 if(threads>(unsigned)max_threads || threads>(unsigned)dim_x || blocks>(uint64_t)grid_x)return -1;
 uint8_t *dh=nullptr,*dt=nullptr,*do_=nullptr,*df=nullptr;
 // All allocations released on every path, including partial allocation failure.
 #define TRY(call) do {e=(call);if(e!=cudaSuccess)goto done;} while(0)
 TRY(cudaMalloc((void**)&dh,80));TRY(cudaMalloc((void**)&dt,32));
 TRY(cudaMalloc((void**)&do_,(size_t)count*32));TRY(cudaMalloc((void**)&df,count));
 TRY(cudaMemcpy(dh,header,80,cudaMemcpyHostToDevice));TRY(cudaMemcpy(dt,target,32,cudaMemcpyHostToDevice));
 nonce_kernel<<<(unsigned)blocks,threads>>>(dh,start,count,dt,do_,df);
 TRY(cudaGetLastError());TRY(cudaDeviceSynchronize());
 TRY(cudaMemcpy(hashes,do_,(size_t)count*32,cudaMemcpyDeviceToHost));
 TRY(cudaMemcpy(flags,df,count,cudaMemcpyDeviceToHost));
 done:
 if(df)cudaFree(df);if(do_)cudaFree(do_);if(dt)cudaFree(dt);if(dh)cudaFree(dh);
 return (int)e;
}
