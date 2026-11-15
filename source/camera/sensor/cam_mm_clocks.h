#ifndef SPRD_CAM_MM_CLOCKS_H
#define SPRD_CAM_MM_CLOCKS_H

struct device;
int sprd_cam_mm_clocks_get(struct device *dev);
void sprd_cam_mm_clocks_put(void);

#endif
