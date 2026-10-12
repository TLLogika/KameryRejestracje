"""USB mode discovery through V4L2; opens no video stream."""
import fcntl
import struct

DEFAULT_SETTINGS = {'rotation_seconds':5,'width':1280,'height':720,'fps':15,'format':'MJPG'}
MIN_ROTATION_SECONDS = 3


def usb_modes(source):
    modes=[]
    try:
        with open(source,'rb',buffering=0) as device:
            for format_index in range(32):
                fmt=bytearray(64)
                struct.pack_into('II',fmt,0,format_index,1)
                try:fcntl.ioctl(device,0xC0405602,fmt)
                except OSError:break
                code=bytes(fmt[44:48])
                name=code.decode('ascii',errors='replace')
                if name not in {'MJPG','YUYV'}:continue
                pixel=struct.unpack('<I',code)[0]
                for size_index in range(64):
                    size=bytearray(44)
                    struct.pack_into('II',size,0,size_index,pixel)
                    try:fcntl.ioctl(device,0xC02C564A,size)
                    except OSError:break
                    kind=struct.unpack_from('I',size,8)[0]
                    if kind==1:
                        sizes=[struct.unpack_from('II',size,12)]
                    else:
                        min_w,max_w,step_w,min_h,max_h,step_h=struct.unpack_from('IIIIII',size,12)
                        sizes=[(w,h) for w,h in ((640,480),(1280,720),(1920,1080)) if min_w<=w<=max_w and min_h<=h<=max_h and (w-min_w)%max(1,step_w)==0 and (h-min_h)%max(1,step_h)==0]
                    for width,height in sizes:
                        rates=[]
                        for rate_index in range(64):
                            interval=bytearray(52)
                            struct.pack_into('IIII',interval,0,rate_index,pixel,width,height)
                            try:fcntl.ioctl(device,0xC034564B,interval)
                            except OSError:break
                            rate_kind,numerator,denominator=struct.unpack_from('III',interval,16)
                            if rate_kind==1:
                                if numerator:rates.append(round(denominator/numerator,3))
                            else:
                                max_num,max_den=struct.unpack_from('II',interval,28)
                                if numerator and max_num and max_den:
                                    rates.extend(r for r in (5,10,15,20,25,30,60) if max_den/max_num<=r<=denominator/numerator)
                                break
                        if rates:modes.append({'format':name,'width':width,'height':height,'fps':sorted(set(rates))})
                    if kind!=1:break
    except OSError:
        return []
    return modes
