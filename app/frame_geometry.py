import math


def crop_for_analysis(frame,roi=None):
    if roi is None:
        return frame,0,0
    height,width=frame.shape[:2]
    x=max(0,math.floor(roi['x']*width));y=max(0,math.floor(roi['y']*height))
    right=min(width,math.ceil((roi['x']+roi['w'])*width))
    bottom=min(height,math.ceil((roi['y']+roi['h'])*height))
    return frame[y:bottom,x:right],x,y
