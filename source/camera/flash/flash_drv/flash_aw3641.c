// SPDX-License-Identifier: GPL-2.0-only
#include <linux/gpio/consumer.h>
#include <linux/leds.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>

#include "sprd_cam.h"
#include "flash_drv.h"

struct aw3641 {
	struct gpio_desc *enable;
	struct gpio_desc *mode;
	struct led_classdev led;
	struct mutex lock;
};

static int aw3641_torch(struct led_classdev *led, enum led_brightness value)
{
	struct aw3641 *flash = container_of(led, struct aw3641, led);

	mutex_lock(&flash->lock);
	/* MODE low selects continuous torch; flash pulses use a different protocol. */
	gpiod_set_value_cansleep(flash->mode, 0);
	gpiod_set_value_cansleep(flash->enable, value != LED_OFF);
	mutex_unlock(&flash->lock);
	return 0;
}

static int aw3641_open(void *data, uint8_t leds)
{
	struct aw3641 *flash = data;

	if (!(leds & SPRD_FLASH_LED0))
		return -EINVAL;
	return led_set_brightness_sync(&flash->led, 1);
}

static int aw3641_close(void *data, uint8_t leds)
{
	struct aw3641 *flash = data;

	return led_set_brightness_sync(&flash->led, LED_OFF);
}

static const struct sprd_flash_driver_ops aw3641_ops = {
	.open_torch = aw3641_open,
	.close_torch = aw3641_close,
	.open_preflash = aw3641_open,
	.close_preflash = aw3641_close,
	.close_highlight = aw3641_close,
};

static int aw3641_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct aw3641 *flash;
	int ret;

	flash = devm_kzalloc(dev, sizeof(*flash), GFP_KERNEL);
	if (!flash)
		return -ENOMEM;
	flash->enable = devm_gpiod_get(dev, "flash-en", GPIOD_OUT_LOW);
	if (IS_ERR(flash->enable))
		return dev_err_probe(dev, PTR_ERR(flash->enable), "enable GPIO\n");
	flash->mode = devm_gpiod_get(dev, "flash-torch-en", GPIOD_OUT_LOW);
	if (IS_ERR(flash->mode))
		return dev_err_probe(dev, PTR_ERR(flash->mode), "mode GPIO\n");
	mutex_init(&flash->lock);
	flash->led.name = "aw3641:white:torch";
	flash->led.max_brightness = 1;
	flash->led.flags = LED_CORE_SUSPENDRESUME;
	flash->led.brightness_set_blocking = aw3641_torch;
	ret = devm_led_classdev_register(dev, &flash->led);
	if (ret)
		return ret;
	platform_set_drvdata(pdev, flash);
	return sprd_flash_register(&aw3641_ops, flash, SPRD_FLASH_REAR);
}

static void aw3641_remove(struct platform_device *pdev)
{
	struct aw3641 *flash = platform_get_drvdata(pdev);

	sprd_flash_register(NULL, NULL, SPRD_FLASH_REAR);
	led_set_brightness_sync(&flash->led, LED_OFF);
}

static void aw3641_shutdown(struct platform_device *pdev)
{
	struct aw3641 *flash = platform_get_drvdata(pdev);

	led_set_brightness_sync(&flash->led, LED_OFF);
}

static const struct of_device_id aw3641_match[] = {
	{ .compatible = "sprd,flash-aw3641" },
	{}
};
MODULE_DEVICE_TABLE(of, aw3641_match);

static struct platform_driver aw3641_driver = {
	.probe = aw3641_probe,
	.remove = aw3641_remove,
	.shutdown = aw3641_shutdown,
	.driver = {
		.name = "flash-aw3641",
		.of_match_table = aw3641_match,
		.suppress_bind_attrs = true,
	},
};

int sprd_flash_aw3641_register(void)
{
	return platform_driver_register(&aw3641_driver);
}

void sprd_flash_aw3641_unregister(void)
{
	platform_driver_unregister(&aw3641_driver);
}
