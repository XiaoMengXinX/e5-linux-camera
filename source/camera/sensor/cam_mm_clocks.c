// SPDX-License-Identifier: GPL-2.0-only
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_clk.h>
#include "cam_mm_clocks.h"

enum { CKG, CFG_BUSMON, MST_BUSMON, MTX_GATE, MTX, BLK_CFG,
       MTX_DEFAULT, MTX_PARENT, CLK_COUNT };
static const char * const names[CLK_COUNT] = {
	"clk_ckg_en", "sys_cfg_mtx_busmon_en", "sys_mst_busmon_en",
	"clk_mm_mtx_data_en", "clk_mm_mtx_data", "clk_blk_cfg_en",
	"clk_mm_mtx_defalut", "clk_mm_mtx_parent"
};
static DEFINE_MUTEX(mm_lock);
static struct clk *clks[CLK_COUNT];
static struct device_node *domain;
static unsigned int users;

int sprd_cam_mm_clocks_get(struct device *dev)
{
	struct device_node *np;
	int i, enabled = 0, ret;

	np = of_parse_phandle(dev->of_node, "power-domains", 0);
	if (!np)
		return -ENODEV;
	mutex_lock(&mm_lock);
	if (users) {
		ret = domain == np ? 0 : -EINVAL;
		if (!ret)
			users++;
		goto out_node;
	}
	for (i = 0; i < CLK_COUNT; i++) {
		clks[i] = of_clk_get_by_name(np, names[i]);
		if (IS_ERR(clks[i])) {
			ret = PTR_ERR(clks[i]);
			dev_err(dev, "cannot get camera clock %s: %d\n", names[i], ret);
			goto put_clks;
		}
	}
	for (i = 0; i <= MTX_GATE; i++) {
		ret = clk_prepare_enable(clks[i]);
		if (ret)
			goto disable;
		enabled++;
	}
	ret = clk_set_parent(clks[MTX], clks[MTX_PARENT]);
	if (ret)
		goto disable;
	ret = clk_prepare_enable(clks[MTX]);
	if (ret)
		goto restore_parent;
	ret = clk_prepare_enable(clks[BLK_CFG]);
	if (ret) {
		clk_disable_unprepare(clks[MTX]);
		goto restore_parent;
	}
	udelay(200);
	domain = np;
	users = 1;
	mutex_unlock(&mm_lock);
	return 0;
restore_parent:
	clk_set_parent(clks[MTX], clks[MTX_DEFAULT]);
disable:
	while (enabled)
		clk_disable_unprepare(clks[--enabled]);
	i = CLK_COUNT;
put_clks:
	while (i)
		clk_put(clks[--i]);
out_node:
	mutex_unlock(&mm_lock);
	of_node_put(np);
	return ret;
}
EXPORT_SYMBOL_GPL(sprd_cam_mm_clocks_get);

void sprd_cam_mm_clocks_put(void)
{
	int i;

	mutex_lock(&mm_lock);
	if (WARN_ON(!users) || --users)
		goto out;
	udelay(200);
	clk_disable_unprepare(clks[BLK_CFG]);
	clk_set_parent(clks[MTX], clks[MTX_DEFAULT]);
	clk_disable_unprepare(clks[MTX]);
	for (i = MTX_GATE; i >= 0; i--)
		clk_disable_unprepare(clks[i]);
	for (i = 0; i < CLK_COUNT; i++)
		clk_put(clks[i]);
	of_node_put(domain);
	domain = NULL;
out:
	mutex_unlock(&mm_lock);
}
EXPORT_SYMBOL_GPL(sprd_cam_mm_clocks_put);
