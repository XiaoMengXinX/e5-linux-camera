#
# sprd_flash_drv.ko
#
# Makefile: for external make invocation
#
# Note:
# - Please refer to modules/sample/Makefile to find out what should be
#   done in this Makefile
#

KO_MODULE_NAME := sprd_flash_drv
KO_MODULE_OUT := $(BSP_MODULES_OUT)/$(KO_MODULE_NAME)

.PHONY: modules modules_install clean

modules:
	@mkdir -p $(KO_MODULE_OUT)
	$(MAKE) -C $(BSP_KERNEL_PATH) M=$(CURDIR) MO=$(KO_MODULE_OUT) $@

modules_install:
	$(MAKE) -C $(BSP_KERNEL_PATH) M=$(CURDIR) MO=$(KO_MODULE_OUT) $@

# Remove the out directory wholly
clean:
	rm -rf $(KO_MODULE_OUT)
