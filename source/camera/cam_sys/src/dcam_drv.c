/*
 * Copyright (C) 2021-2022 UNISOC Communications Inc.
 *
 * This software is licensed under the terms of the GNU General Public
 * License version 2, as published by the Free Software Foundation, and
 * may be copied, distributed, and modified under those terms.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 */

#include <linux/of_platform.h>
#include <linux/clk.h>
#include <linux/err.h>
#include <linux/mfd/syscon.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/of_irq.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <sprd_mm.h>

#include "dcam_core.h"

#ifdef pr_fmt
#undef pr_fmt
#endif
#define pr_fmt(fmt) "DCAM_DRV: %d %d %s : " fmt, current->pid, __LINE__, __func__

unsigned long g_dcam_regbase[DCAM_ID_MAX];
unsigned long g_dcam_aximbase[DCAM_ID_MAX];
unsigned long g_dcam_phys_base[DCAM_ID_MAX];
unsigned long g_dcam_mmubase[DCAM_ID_MAX];
unsigned long g_dcam_fmcubase;

static void dcam_drv_put_clocks(struct cam_hw_soc_info *soc)
{
	if (!IS_ERR_OR_NULL(soc->core_eb))
		clk_put(soc->core_eb);
	soc->core_eb = NULL;
	if (!IS_ERR_OR_NULL(soc->axi_eb))
		clk_put(soc->axi_eb);
	soc->axi_eb = NULL;
	if (!IS_ERR_OR_NULL(soc->mtx_en))
		clk_put(soc->mtx_en);
	soc->mtx_en = NULL;
	if (!IS_ERR_OR_NULL(soc->blk_cfg_en))
		clk_put(soc->blk_cfg_en);
	soc->blk_cfg_en = NULL;
	if (!IS_ERR_OR_NULL(soc->tck_en))
		clk_put(soc->tck_en);
	soc->tck_en = NULL;
	if (!IS_ERR_OR_NULL(soc->clk))
		clk_put(soc->clk);
	soc->clk = NULL;
	if (!IS_ERR_OR_NULL(soc->clk_parent))
		clk_put(soc->clk_parent);
	soc->clk_parent = NULL;
	if (!IS_ERR_OR_NULL(soc->bpc_clk))
		clk_put(soc->bpc_clk);
	soc->bpc_clk = NULL;
	if (!IS_ERR_OR_NULL(soc->bpc_clk_parent))
		clk_put(soc->bpc_clk_parent);
	soc->bpc_clk_parent = NULL;
	if (!IS_ERR_OR_NULL(soc->axi_clk))
		clk_put(soc->axi_clk);
	soc->axi_clk = NULL;
	if (!IS_ERR_OR_NULL(soc->axi_clk_parent))
		clk_put(soc->axi_clk_parent);
	soc->axi_clk_parent = NULL;
	if (!IS_ERR_OR_NULL(soc->mtx_clk))
		clk_put(soc->mtx_clk);
	soc->mtx_clk = NULL;
	if (!IS_ERR_OR_NULL(soc->mtx_clk_parent))
		clk_put(soc->mtx_clk_parent);
	soc->mtx_clk_parent = NULL;
	if (!IS_ERR_OR_NULL(soc->blk_cfg_clk))
		clk_put(soc->blk_cfg_clk);
	soc->blk_cfg_clk = NULL;
	if (!IS_ERR_OR_NULL(soc->blk_cfg_clk_parent))
		clk_put(soc->blk_cfg_clk_parent);
	soc->blk_cfg_clk_parent = NULL;
	soc->clk_default = NULL;
	soc->bpc_clk_default = NULL;
	soc->axi_clk_default = NULL;
	soc->mtx_clk_default = NULL;
	soc->blk_cfg_clk_default = NULL;
}

static void dcam_drv_release(void *data)
{
	struct cam_hw_info *hw = data;
	struct cam_hw_soc_info *soc = hw->soc_dcam, *lite = hw->soc_dcam_lite;
	unsigned long main_mmu = g_dcam_mmubase[0];
	unsigned long lite_mmu = lite && lite->count && soc->count < DCAM_ID_MAX ?
		g_dcam_mmubase[soc->count] : 0;
	int i;

	for (i = 0; i < DCAM_ID_MAX; i++) {
		if (hw->ip_dcam[i]) {
			if (hw->ip_dcam[i]->reg_base)
				iounmap((void __iomem *)hw->ip_dcam[i]->reg_base);
			if (hw->ip_dcam[i]->irq_no)
				irq_dispose_mapping(hw->ip_dcam[i]->irq_no);
			hw->ip_dcam[i]->reg_base = 0;
			hw->ip_dcam[i]->phy_base = 0;
			hw->ip_dcam[i]->irq_no = 0;
		}
		g_dcam_regbase[i] = 0;
		g_dcam_phys_base[i] = 0;
		g_dcam_aximbase[i] = 0;
		g_dcam_mmubase[i] = 0;
	}
	if (main_mmu)
		iounmap((void __iomem *)main_mmu);
	if (lite_mmu)
		iounmap((void __iomem *)lite_mmu);
	if (g_dcam_fmcubase)
		iounmap((void __iomem *)g_dcam_fmcubase);
	g_dcam_fmcubase = 0;
	if (soc->axi_reg_base)
		iounmap((void __iomem *)soc->axi_reg_base);
	soc->axi_reg_base = 0;
	dcam_drv_put_clocks(soc);
	soc->count = 0;
	soc->pdev = NULL;
	if (lite) {
		if (lite->axi_reg_base)
			iounmap((void __iomem *)lite->axi_reg_base);
		lite->axi_reg_base = 0;
		dcam_drv_put_clocks(lite);
		if (lite->pdev)
			put_device(&lite->pdev->dev);
		lite->pdev = NULL;
		lite->count = 0;
	}
	hw->pdev = NULL;
}

#if defined(PROJ_QOGIRN6PRO) || defined(PROJ_QOGIRN6L)
static int dcam_drv_get_clocks(struct device_node *dn, struct cam_hw_soc_info *soc)
{
#define GET_CLK(field, name) do { \
	soc->field = of_clk_get_by_name(dn, name); \
	if (IS_ERR(soc->field)) return PTR_ERR(soc->field); \
} while (0)
	GET_CLK(core_eb, "dcam_eb");
	GET_CLK(clk, "dcam_clk");
	GET_CLK(clk_parent, "dcam_clk_parent");
	soc->clk_default = clk_get_parent(soc->clk);
	GET_CLK(mtx_en, "dcam_mtx_en");
	GET_CLK(tck_en, "dcam_tck_en");
	GET_CLK(blk_cfg_en, "dcam_blk_cfg_en");
	GET_CLK(axi_clk, "dcam_axi_clk");
	GET_CLK(axi_clk_parent, "dcam_axi_clk_parent");
	soc->axi_clk_default = clk_get_parent(soc->axi_clk);
	GET_CLK(mtx_clk, "dcam_mtx_clk");
	GET_CLK(mtx_clk_parent, "dcam_mtx_clk_parent");
	soc->mtx_clk_default = clk_get_parent(soc->mtx_clk);
	GET_CLK(blk_cfg_clk, "dcam_blk_cfg_clk");
	GET_CLK(blk_cfg_clk_parent, "dcam_blk_cfg_clk_parent");
	soc->blk_cfg_clk_default = clk_get_parent(soc->blk_cfg_clk);
#undef GET_CLK
	return 0;
}
#endif

static int dcam_drv_lite_dt_parse(struct device_node *dn, struct cam_hw_info *hw_info)
{
	int ret = 0;
	struct device_node *lite_node = NULL;
	struct cam_hw_soc_info *soc_dcam = NULL;
	struct cam_hw_soc_info *soc_dcam_lite = NULL;
	struct cam_hw_ip_info *ip_dcam = NULL;
	struct device_node *iommu_node = NULL;
	uint32_t count = 0, dcam_if_count = 0;
	void __iomem *reg_base = NULL;
	int i = 0, j = 0, irq = 0;
	struct resource reg_res = {0}, irq_res = {0};
	uint32_t args[2], all_rst[2];
	char dcam_name[20];

	if (!dn || !hw_info) {
		pr_err("fail to get dn %p hw info %p\n", dn, hw_info);
		ret = -EINVAL;
		goto out;
	}

	lite_node = of_parse_phandle(dn, "sprd,dcam-lite", 0);
	if (lite_node == NULL) {
		pr_info("don't have dcam lite\n");
		return ret;
	}
	soc_dcam_lite = hw_info->soc_dcam_lite;
	soc_dcam_lite->pdev = of_find_device_by_node(lite_node);
	if (soc_dcam_lite->pdev == NULL) {
		pr_err("fail to get lite pdev\n");
		ret = -EPROBE_DEFER;
		goto out;
	}
	pr_info("sprd s_lite_pdev name %s\n", soc_dcam_lite->pdev->name);

	if (of_device_is_compatible(lite_node, "sprd,dcam_lite")) {
		if (of_property_read_u32_index(lite_node, "sprd,dcam-lite-count", 0, &count)) {
			pr_err("fail to parse the property of sprd,isp-count\n");
			ret = -EINVAL;
			goto out;
		}
		if (!count || count > DCAM_ID_MAX - hw_info->soc_dcam->count) {
			ret = -EINVAL;
			goto out;
		}
		soc_dcam_lite->count = count;

		soc_dcam_lite->core_eb = of_clk_get_by_name(lite_node, "dcam_lite_eb");
		if (IS_ERR(soc_dcam_lite->core_eb)) {
			ret = PTR_ERR(soc_dcam_lite->core_eb);
			goto out;
		}
		soc_dcam_lite->mtx_en = of_clk_get_by_name(lite_node, "dcam_lite_mtx_en");
		if (IS_ERR(soc_dcam_lite->mtx_en)) {
			ret = PTR_ERR(soc_dcam_lite->mtx_en);
			goto out;
		}
		soc_dcam_lite->clk = of_clk_get_by_name(lite_node, "dcam_lite_clk");
		if (IS_ERR(soc_dcam_lite->clk)) {
			ret = PTR_ERR(soc_dcam_lite->clk);
			goto out;
		}
		soc_dcam_lite->clk_parent = of_clk_get_by_name(lite_node, "dcam_lite_clk_parent");
		if (IS_ERR(soc_dcam_lite->clk_parent)) {
			ret = PTR_ERR(soc_dcam_lite->clk_parent);
			goto out;
		}
		soc_dcam_lite->axi_clk = of_clk_get_by_name(lite_node, "dcam_lite_axi_clk");
		if (IS_ERR(soc_dcam_lite->axi_clk)) {
			ret = PTR_ERR(soc_dcam_lite->axi_clk);
			goto out;
		}
		soc_dcam_lite->axi_clk_parent = of_clk_get_by_name(lite_node, "dcam_lite_axi_clk_parent");
		if (IS_ERR(soc_dcam_lite->axi_clk_parent)) {
			ret = PTR_ERR(soc_dcam_lite->axi_clk_parent);
			goto out;
		}
		soc_dcam_lite->clk_default = clk_get_parent(soc_dcam_lite->clk);
		soc_dcam_lite->axi_clk_default = clk_get_parent(soc_dcam_lite->axi_clk);

		ret = cam_kernel_adapt_syscon_get_args_by_name(lite_node, "lite_all_reset", ARRAY_SIZE(all_rst), all_rst);
		if (ret) {
			pr_err("fail to get lite all reset syscon\n");
			ret = -EINVAL;
			goto out;
		}

		soc_dcam = hw_info->soc_dcam;
		dcam_if_count = soc_dcam->count;
		for (i = 0; i < count; i++) {
			ip_dcam = hw_info->ip_dcam[i + dcam_if_count];
			ip_dcam->idx = i + dcam_if_count;

			irq = of_irq_to_resource(lite_node, i, &irq_res);
			if (irq <= 0) {
				pr_err("fail to get DCAM%d irq, error: %d\n", i + dcam_if_count, irq);
				ret = -EINVAL;
				goto out;
			}
			ip_dcam->irq_no = (uint32_t) irq;

			/* DCAM register mapping */
			if (of_address_to_resource(lite_node, i, &reg_res)) {
				pr_err("fail to get DCAM%d phy addr\n", i + dcam_if_count);
				ret = -EINVAL;
				goto out;
			}
			ip_dcam->phy_base = (unsigned long) reg_res.start;
			g_dcam_phys_base[i + dcam_if_count] = ip_dcam->phy_base;
			pr_debug("dcamlite phys reg base is %lx\n", g_dcam_phys_base[dcam_if_count]);

			reg_base = ioremap(reg_res.start, reg_res.end - reg_res.start + 1);
			if (!reg_base) {
				pr_err("fail to map DCAM%d reg base\n", i + dcam_if_count);
				ret = -EINVAL;
				goto out;
			}
			ip_dcam->reg_base = (unsigned long) reg_base;
			g_dcam_regbase[i + dcam_if_count] = (unsigned long)reg_base;

			pr_info("DCAM%d reg: %s 0x%lx %lx, irq: %s %u\n", i + dcam_if_count,
				reg_res.name, ip_dcam->phy_base, ip_dcam->reg_base,
				irq_res.name, ip_dcam->irq_no);

			sprintf(dcam_name, "lite%d_reset", i);
			if (!cam_kernel_adapt_syscon_get_args_by_name(lite_node, dcam_name,
				ARRAY_SIZE(args), args)) {
				ip_dcam->syscon.rst = args[0];
				ip_dcam->syscon.rst_mask = args[1];
			} else {
				pr_err("fail to get dcam_lite%d reset syscon\n", i + dcam_if_count);
				ret = -EINVAL;
				goto out;
			}
			#if defined (PROJ_QOGIRN6L)
			sprintf(dcam_name, "lite%d_mipi_reset", i);
			if (!cam_kernel_adapt_syscon_get_args_by_name(lite_node, dcam_name,
				ARRAY_SIZE(args), args)) {
				ip_dcam->syscon.rst_mipi_mask = args[1];
			} else {
				pr_err("fail to get dcam_lite_mipi%d reset syscon\n", i + dcam_if_count);
				ret = -EINVAL;
				goto out;
			}
			#endif
			ip_dcam->syscon.all_rst = all_rst[0];
			ip_dcam->syscon.all_rst_mask = all_rst[1];
		}

		if (of_address_to_resource(lite_node, i, &reg_res)) {
			pr_err("fail to get AXIM phy addr\n");
			ret = -EINVAL;
			goto out;
		}

		reg_base = ioremap(reg_res.start, reg_res.end - reg_res.start + 1);
		if (!reg_base) {
			pr_err("fail to map AXIM reg base\n");
			ret = -EINVAL;
			goto out;
		}
		soc_dcam_lite->axi_reg_base = (unsigned long)reg_base;
		pr_info("dcam_lite axi_reg_base 0x%lx, count %d\n",soc_dcam_lite->axi_reg_base,count);
		for (j = 0; j < count; j++)
			g_dcam_aximbase[j + dcam_if_count] = (unsigned long)reg_base;

		iommu_node = of_parse_phandle(lite_node, "iommus", 0);
		if (iommu_node) {
			reg_base = of_iomap(iommu_node, 1);
			if (!reg_base)
				pr_err("fail to map DCAM LITE IOMMU base\n");
			else {
				for (j = 0; j < count; j++)
					g_dcam_mmubase[j + dcam_if_count] = (unsigned long)reg_base;
			}
			of_node_put(iommu_node);
		}
		pr_info("DCAM LITE IOMMU Base  0x%lx\n", (unsigned long)reg_base);
	} else {
		ret = -EINVAL;
	}
out:
	of_node_put(lite_node);
	return ret;
}

int dcam_drv_dt_parse(struct platform_device *pdev,
			struct cam_hw_info *hw_info,
			uint32_t *dcam_count)
{
	struct cam_hw_soc_info *soc_dcam = NULL;
	struct cam_hw_ip_info *ip_dcam = NULL;
	struct device_node *dn = NULL;
	struct device_node *qos_node = NULL;
	struct device_node *iommu_node = NULL;
	struct regmap *ahb_map = NULL;
	void __iomem *reg_base = NULL;
	struct resource reg_res = {0}, irq_res = {0};
	uint32_t count = 0, prj_id = 0;
	int i = 0, irq = 0;
	uint32_t args[2];
	char dcam_name[20];
	int ret = 0;

	pr_info("start dcam dts parse\n");

	if (!pdev || !hw_info || !dcam_count) {
		pr_err("fail to get pdev %p hw info %p\n", pdev, hw_info);
		return -EINVAL;
	}

	dn = pdev->dev.of_node;
	if (unlikely(!dn)) {
		pr_err("fail to get a valid device node\n");
		return -EINVAL;
	}

	ret = devm_add_action_or_reset(&pdev->dev, dcam_drv_release, hw_info);
	if (ret)
		return ret;

	ahb_map = syscon_regmap_lookup_by_phandle(dn, "sprd,cam-ahb-syscon");
	if (IS_ERR_OR_NULL(ahb_map)) {
		pr_err("fail to get sprd,cam-ahb-syscon\n");
		return ahb_map ? PTR_ERR(ahb_map) : -EINVAL;
	}

	ret = hw_info->cam_ioctl(hw_info, CAM_HW_GET_CSI_SWITCH, dn);
	if (ret)
		return ret;

	if (of_property_read_u32(dn, "sprd,dcam-count", &count)) {
		pr_err("fail to parse the property of sprd,dcam-count\n");
		return -EINVAL;
	}

	if (of_property_read_u32(dn, "sprd,project-id", &prj_id))
		pr_info("fail to parse the property of sprd,projectj-id\n");

	/* bounded kernel device node */
	hw_info->pdev = pdev;
	hw_info->prj_id = (enum cam_prj_id) prj_id;

	if (!count || count > DCAM_ID_MAX) {
		pr_err("fail to get a valid dcam count, count: %u\n", count);
		return -EINVAL;
	}

	pr_info("dev: %s, full name: %s, cam_ahb_gpr: %px, count: %u \n",
		pdev->name, dn->full_name, ahb_map, count);

	iommu_node = of_parse_phandle(dn, "iommus", 0);
	if (iommu_node) {
#if (LINUX_VERSION_CODE < KERNEL_VERSION(5, 4, 0))
		reg_base = of_iomap(iommu_node, 0);
#else
		reg_base = of_iomap(iommu_node, 1);
#endif
		if (!reg_base)
			pr_err("fail to map DCAM IOMMU base\n");
		else {
			for (i = 0; i < count; i++)
				g_dcam_mmubase[i] = (unsigned long)reg_base;
		}
		of_node_put(iommu_node);
	}
	pr_info("DCAM IOMMU Base 0x%lx\n", g_dcam_mmubase[0]);

	/* Start dcam soc related dt parse */
	soc_dcam = hw_info->soc_dcam;
	soc_dcam->count = count;
	soc_dcam->pdev = pdev;
	/* AHB bus register mapping */
	soc_dcam->cam_ahb_gpr = ahb_map;
	/* qos dt parse */
	qos_node = of_parse_phandle(dn, "dcam_qos", 0);
	if (qos_node) {
		uint8_t val;

		if (of_property_read_u8(qos_node, "awqos-high", &val)) {
			pr_warn("warning: isp awqos-high reading fail.\n");
			val = 0xD;
		}
		soc_dcam->awqos_high = (uint32_t)val;

		if (of_property_read_u8(qos_node, "awqos-low", &val)) {
			pr_warn("warning: isp awqos-low reading fail.\n");
			val = 0xA;
		}
		soc_dcam->awqos_low = (uint32_t)val;

		if (of_property_read_u8(qos_node, "arqos", &val)) {
			pr_warn("warning: isp arqos-high reading fail.\n");
			val = 0xA;
		}
		soc_dcam->arqos_high = val;
		soc_dcam->arqos_low = val;

		of_node_put(qos_node);
		pr_info("get dcam qos node. r: %d %d w: %d %d\n",
			soc_dcam->arqos_high, soc_dcam->arqos_low,
			soc_dcam->awqos_high, soc_dcam->awqos_low);
	} else {
		soc_dcam->awqos_high = 0xD;
		soc_dcam->awqos_low = 0xA;
		soc_dcam->arqos_high = 0xA;
		soc_dcam->arqos_low = 0xA;
	}

	/* read dcam clk */
#if defined(PROJ_QOGIRN6PRO) || defined(PROJ_QOGIRN6L)
	ret = dcam_drv_get_clocks(dn, soc_dcam);
#else
	ret = hw_info->cam_ioctl(hw_info, CAM_HW_GET_DCAM_DTS_CLK, dn);
#endif
	if (ret)
		goto err_iounmap;

	for (i = 0; i < count; i++) {
		ip_dcam = hw_info->ip_dcam[i];
		/* DCAM index */
		ip_dcam->idx = i;

		/* irq */
		irq = of_irq_to_resource(dn, i, &irq_res);
		if (irq <= 0) {
			pr_err("fail to get DCAM%d irq, error: %d\n", i, irq);
			goto err_iounmap;
		}
		ip_dcam->irq_no = (uint32_t) irq;

		/* DCAM register mapping */
		if (of_address_to_resource(dn, i, &reg_res)) {
			pr_err("fail to get DCAM%d phy addr\n", i);
			goto err_iounmap;
		}
		ip_dcam->phy_base = (unsigned long) reg_res.start;
		g_dcam_phys_base[i] = ip_dcam->phy_base;
		pr_debug("dcam phys reg base is %lx\n", g_dcam_phys_base[0]);
		reg_base = ioremap(reg_res.start, reg_res.end - reg_res.start + 1);
		if (!reg_base) {
			pr_err("fail to map DCAM%d reg base\n", i);
			goto err_iounmap;
		}
		ip_dcam->reg_base = (unsigned long) reg_base;
		g_dcam_regbase[i] = (unsigned long)reg_base;

		pr_info("DCAM%d reg: %s 0x%lx %lx, irq: %s %u\n", i,
			reg_res.name, ip_dcam->phy_base, ip_dcam->reg_base,
			irq_res.name, ip_dcam->irq_no);

		sprintf(dcam_name, "dcam%d_reset", i);
		if (!cam_kernel_adapt_syscon_get_args_by_name(dn, dcam_name,
			ARRAY_SIZE(args), args)) {
			ip_dcam->syscon.rst = args[0];
			ip_dcam->syscon.rst_mask = args[1];
		} else {
			pr_err("fail to get dcam%d reset syscon\n", i);
			goto err_iounmap;
		}
	}

	ret = hw_info->cam_ioctl(hw_info, CAM_HW_GET_ALL_RST, dn);
	if (ret)
		goto err_iounmap;

	ret = hw_info->cam_ioctl(hw_info, CAM_HW_GET_AXI_BASE, dn);
	if (ret) {
#if defined(PROJ_QOGIRN6PRO) || defined(PROJ_QOGIRN6L)
		/* The adapter unmaps AXI on its FMCU failure path. */
		soc_dcam->axi_reg_base = 0;
#endif
		goto err_iounmap;
	}

	if (hw_info->soc_dcam_lite) {
		hw_info->soc_dcam_lite->cam_ahb_gpr = ahb_map;
		ret = dcam_drv_lite_dt_parse(dn, hw_info);
		if (ret)
			goto err_iounmap;
		*dcam_count = count + hw_info->soc_dcam_lite->count;
	} else
		*dcam_count = count;

	return 0;

err_iounmap:
	return ret < 0 ? ret : -ENXIO;
}
