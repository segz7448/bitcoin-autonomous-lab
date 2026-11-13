// One implementation shared by the CUDA device and CPU-only algorithm tests.
#pragma once
#include <stdint.h>
#ifndef BAL_DEVICE
#define BAL_DEVICE
#endif
BAL_DEVICE static uint32_t rotr(uint32_t x, unsigned n) { return (x>>n)|(x<<(32-n)); }
BAL_DEVICE static void compress(uint32_t* s, const uint8_t* p) {
 const uint32_t k[64]={
 0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
 0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
 0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
 0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
 0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
 0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
 0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
 0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
 uint32_t w[64];
 for(int i=0;i<16;i++) w[i]=((uint32_t)p[i*4]<<24)|((uint32_t)p[i*4+1]<<16)|((uint32_t)p[i*4+2]<<8)|p[i*4+3];
 for(int i=16;i<64;i++) { uint32_t a=w[i-15],b=w[i-2]; w[i]=w[i-16]+(rotr(a,7)^rotr(a,18)^(a>>3))+w[i-7]+(rotr(b,17)^rotr(b,19)^(b>>10)); }
 uint32_t a=s[0],b=s[1],c=s[2],d=s[3],e=s[4],f=s[5],g=s[6],h=s[7];
 for(int i=0;i<64;i++) {
  uint32_t t1=h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+k[i]+w[i];
  uint32_t t2=(rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c));
  h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
 }
 s[0]+=a;s[1]+=b;s[2]+=c;s[3]+=d;s[4]+=e;s[5]+=f;s[6]+=g;s[7]+=h;
}
BAL_DEVICE static void sha256(const uint8_t* input, unsigned len, uint8_t* out) {
 uint32_t s[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
 unsigned full=len/64;
 for(unsigned i=0;i<full;i++) compress(s,input+64*i);
 uint8_t tail[128]={0}; unsigned rem=len%64;
 for(unsigned i=0;i<rem;i++) tail[i]=input[full*64+i];
 tail[rem]=0x80; unsigned padded=rem<56?64:128; uint64_t bits=(uint64_t)len*8;
 for(int i=0;i<8;i++) tail[padded-1-i]=(uint8_t)(bits>>(i*8));
 compress(s,tail); if(padded==128) compress(s,tail+64);
 for(int i=0;i<32;i++) out[i]=(uint8_t)(s[i/4]>>(24-8*(i%4)));
}
BAL_DEVICE static void sha256d(const uint8_t* header, uint32_t nonce, uint8_t* out) {
 uint8_t h[80],first[32]; for(int i=0;i<80;i++) h[i]=header[i];
 for(int i=0;i<4;i++) h[76+i]=(uint8_t)(nonce>>(8*i));
 sha256(h,80,first);sha256(first,32,out);
}
BAL_DEVICE static bool meets_target(const uint8_t* hash,const uint8_t* target) {
 for(int i=31;i>=0;i--) {if(hash[i]<target[i])return true;if(hash[i]>target[i])return false;}
 return true;
}
