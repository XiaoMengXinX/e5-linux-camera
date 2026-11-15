/* SPDX-License-Identifier: GPL-2.0 */
#ifndef CAM_SYSTEM_BUFFER_H
#define CAM_SYSTEM_BUFFER_H

#include <linux/types.h>

struct dma_buf;
struct device;
int cam_system_heap_register(struct device *dev);
void cam_system_heap_unregister(void);
struct dma_buf *cam_system_buffer_alloc(unsigned long len, u32 fd_flags);
void *cam_system_buffer_iommu_data(struct dma_buf *dmabuf);

#endif
