# -*- coding: utf-8 -*-#
# -------------------------------------------------------------------------------
# Name:         FF_MLA_Vision10_3TRC
# Description:  
# Author:       Administrator
# Date:         2021/9/16
# -------------------------------------------------------------------------------
# -*- coding: utf-8 -*-#
# -------------------------------------------------------------------------------
# Name:         FF_MLA_Vision10_2TRC
# Description:
# Author:       Administrator
# Date:         2021/9/16
# -------------------------------------------------------------------------------
# -------------------------------------------------------------------------------
# Name:         FF_MLA_Vision2
# Description:
# 2021年6月7日 V1 第一个版本 融合 FFusion的 V3版本 和  MLA的V2 版本
# 2021年6月9日 V2 第二个版本 融合 FFusion的 V3版本 和  MLA的V7版本
# 2021年6月17日 V3 第三个版本 为DRIVE数据集 适配 584 的分辨率
# 2021年6月21日 V4 第四个版本 为多分辨率训练扩展模型结构
# 2021年6月21日 V5 第五个版本  修正原来的flateen方式，改为使用 Conv 进行Embed 然后查看结果
# 2021年7月2日 V6 第六个版本 为了降低参数 缩减通道 同时 将最后一层没有加入Transformer的删去
#                修改了最后出来的自注意力的处理方式 原来是Sigmoid方式
#               现在修正为  同时施加通道维度和空间维度的 Softmax 然后进行处理。
# 2021年7月14日 更新： 此版本由于 通道压缩过于巨大 且可能是由于把最底层也加入Transformer的缘故，训练极度不稳定，预计在下个版本做出修正。
# 2021年7月14日 V7 第七个版本 延续上个版本的降低参数思路， 首先缩减通道，起始的64通降低为 16通道，然后削减掉一层，原有设计为5层，现在削减为4层。 最后 不同于Vision5中的
#              在 上一个版本中 我们将最底层也加入了Transformer，但是这可能损害了最底层的语义信息 导致网络极度的不稳定，因此这个版本将最底层调出 查看结果。
#               除此之外 所有的设定全部都是  与 Vision4的设定相同 也就是在Embedding那里  使用的是 Adaptive + Global polling 然后再使用卷积一口气直接卷积为 固定尺寸
# 2021年7月14日 V8 第八个版本 此版本是伴生 7版本存在的  由于 等同于 Vison2 和 Vision4的关系。 在这里 关于通道和层数的设定是集成V7的
#               除此意外，  再Embedding部分  使用的是 Global Polling压缩到一个维度之后， 直接使用Linear Projection 将特征映射的  而不是使用卷积进行映射
#                   但是这里有个问题 由于少了一层 原来是 74*74进行映射 映射到1024维度 参数大小还可以接受
#                   但是现在由于少了一层 末层大小为 148 * 148 此时进行映射 参数大小直接到达 300MB 完全不满足轻量化的条件  而如果是缩小到32 * 32的话 那就和 Vision6版本没有区别 因此这个版本废弃
#               此版本废弃！！
# 2021年7月15日 V9 第九个版本 此版本是基于6版本的演变型号，在Fin_test4中，观察到实验曲线震荡非常严重，考虑到可能是通道带来的影响 因此这个版本将通道下修为1/2 查看结果
# 2021年7月19日 V10 第十个版本 基于NNI Search#8号搜索的结果， 第五个 第七个 第九个版本 代表了V4及其轻量化家族，已经确认结果不行，因此予以废弃。 此版本基于Vision2 版本进行演变，将通道降低为16通，
#                   同时不删去最底层，查看结果。
# 2021年7月19日 V11 第11个版本 基于NNI Search#8号搜索的结果， 第五个 第七个 第九个版本 代表了V4及其轻量化家族，已经确认结果不行，因此予以废弃。 此版本基于Vision2 版本进行演变，将通道降低为32通，
# #                   同时不删去最底层，查看结果。
# 2021年9月15日 V12 第12个版本  为了进行参数skip connection数量调节  本版本为只含有1层 skip connection 的版本 只有最顶层 分辨率最大的那一层才有Trc
# 2021年9月16日 V13 第13个版本  为了进行参数skip connection数量调节  本版本为只含有2层 skip connection 的版本 只有最顶层 和 次顶层 分辨率最大的那两层才有Trc
# 2021年9月16日 V14 第14个版本  为了进行参数skip connection数量调节  本版本为只含有3层 skip connection 的版本 只有 分辨率最大的前三层才有Trc
# Author:       Administrator
# Date:         2021/6/9
# -------------------------------------------------------------------------------


import torch as t
import torch
import os
import random
import time
import torch.nn as nn
import torch.nn.functional as F


from torchsummary import summary


### 模块1  深度可分离卷积 3*3 模块

class depthwise_separable_conv(nn.Module):
    def __init__(self, nin, nout,depth_kernel_size = 3,depth_padding = 1):
        super(depthwise_separable_conv, self).__init__()
        self.depthwise = nn.Conv2d(nin, nin, kernel_size=depth_kernel_size, padding=depth_padding, groups=nin)
        self.pointwise = nn.Conv2d(nin, nout, kernel_size=1)
        self.bn = nn.BatchNorm2d(nout)
        self.activtion = nn.ReLU(inplace= True)

    def forward(self, x):
        out = self.depthwise(x)
        out = self.pointwise(out)
        out = self.bn(out)
        out = self.activtion(out)
        return out

# test part
# depwise_conv_3_3 = depthwise_separable_conv(12,16)
# input = torch.randn(size= [1,12,45,45])
# output = depwise_conv_3_3(input) #torch.Size([1, 16, 45, 45])
# print(output.shape)
# Test OK !

### 模块2  1*1 卷积配合bn和relu

class kernel_1_1_conv_bn_relu(nn.Module):
    def __init__(self, nin, nout):
        super(kernel_1_1_conv_bn_relu, self).__init__()
        self.conv1_1 = nn.Conv2d(nin, nout, kernel_size=1, padding=0,bias= False)
        self.bn = nn.BatchNorm2d(nout)
        self.activtion = nn.ReLU(inplace= True)

    def forward(self, x):
        out = self.conv1_1(x)
        out = self.bn(out)
        out = self.activtion(out)
        return out

# test part
# depwise_conv_1_1 = kernel_1_1_conv_bn_relu(12,16)
# input = torch.randn(size= [1,12,45,45])
# output = depwise_conv_1_1(input) #torch.Size([1, 16, 45, 45])
# print(output.shape)
# Test OK !


### 模块3  空间自注意力模块
class SCSEModule(nn.Module):
    def __init__(self, in_channels, reduction=16):
        super().__init__()
        self.cSE = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(in_channels, in_channels // reduction, 1),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels // reduction, in_channels, 1),
            nn.Sigmoid(),
        )
        self.sSE = nn.Sequential(nn.Conv2d(in_channels, 1, 1), nn.Sigmoid())

    def forward(self, x):
        return x * self.cSE(x) + x * self.sSE(x)

# test part
# cbam = SCSEModule(12,reduction=2)
# input = torch.randn(size= [1,12,45,45])
# output = cbam(input) #torch.Size([1, 12, 45, 45])
# print(output.shape)
# Test OK !
class FeatureFusionModule(nn.Module):
    def __init__(self,nin:int,nout:int):
        super(FeatureFusionModule, self).__init__()
        self.conv1_1 = kernel_1_1_conv_bn_relu( nin,nin // 2)
        self.cbam =  SCSEModule(in_channels= nin,reduction= 4)
        self.depthwiseconv3_3 = depthwise_separable_conv(nin,nin // 2)
        self.channelReduction = nn.Conv2d(2 * nin, nout, kernel_size=1, stride=1, padding=0)
        #self.bn = nn.BatchNorm2d(nout)
        #self.activtion = nn.ReLU(inplace=True)

    def forward(self,x_skip, x_up):
        p_1 = self.conv1_1(x_skip)
        p_2 = self.cbam(x_skip)
        p_3 = self.depthwiseconv3_3(x_skip)
        # 维度融合
        p = torch.cat([p_1,p_2,p_3],dim= 1)
        x = self.channelReduction(p)
        # print(x.shape)
        # print(x_up.shape)
        x += x_up
        #x = self.activtion(x)
        return x

    def _init_weight(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                torch.nn.init.kaiming_normal_(m.weight)
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

## 1.最最基础版本的Unet结构
class DoubleConv(nn.Module):
    """(convolution => [BN] => ReLU) * 2"""

    def __init__(self, in_channels, out_channels, mid_channels=None):
        super().__init__()
        if not mid_channels:
            mid_channels = out_channels
        self.double_conv = nn.Sequential(
            nn.Conv2d(in_channels, mid_channels, kernel_size=3, padding=1),
            nn.BatchNorm2d(mid_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_channels, out_channels, kernel_size=3, padding=1),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )

    def forward(self, x):
        return self.double_conv(x)


class Down(nn.Module):
    """Downscaling with maxpool then double conv"""

    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.maxpool_conv = nn.Sequential(
            nn.MaxPool2d(2),
            DoubleConv(in_channels, out_channels)
        )

    def forward(self, x):
        return self.maxpool_conv(x)


class Up(nn.Module):
    """Upscaling then double conv"""

    def __init__(self, in_channels, out_channels, bilinear=True):
        super().__init__()
        self.ffusion = FeatureFusionModule(in_channels // 2, in_channels // 2)
        # if bilinear, use the normal convolutions to reduce the number of channels
        if bilinear:
            self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
            self.conv = DoubleConv(in_channels // 2, out_channels, in_channels // 4)
        else:
            self.up = nn.ConvTranspose2d(in_channels , in_channels // 2, kernel_size=2, stride=2)
            self.conv = DoubleConv(in_channels, out_channels)


    def forward(self, x1, x2):
        x1 = self.up(x1)
        # print(x1.shape)
        # print(x2.shape)
        # 双线性插值上采样之后 将大小不符合的部分做一个padding  将周围区域填充0 然后加入网络中
        # input is CHW
        # 双线性插值之后 这里的大小是一模一样的 不需要修改
        # diffY = x2.size()[2] - x1.size()[2]
        # diffX = x2.size()[3] - x1.size()[3]
        #
        # x1 = F.pad(x1, [diffX // 2, diffX - diffX // 2,
        #                 diffY // 2, diffY - diffY // 2])
        # if you have padding issues, see
        # https://github.com/HaiyongJiang/U-Net-Pytorch-Unstructured-Buggy/commit/0e854509c2cea854e247a9c615f175f76fbb2e3a
        # https://github.com/xiaopeng-liao/Pytorch-UNet/commit/8ebac70e633bac59fc22bb5195e513d5832fb3bd
        # x = torch.cat([x2, x1], dim=1)
        x = self.ffusion(x2,x1)
        # print(x.shape)
        # print()
        return self.conv(x)


class OutConv(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(OutConv, self).__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=1)

    def forward(self, x):
        return self.conv(x)






from itertools import repeat
import collections.abc

# From PyTorch internals
def _ntuple(n):
    def parse(x):
        if isinstance(x, collections.abc.Iterable):
            return x
        return tuple(repeat(x, n))
    return parse

to_2tuple = _ntuple(2)

# 将
class PatchEmbed(nn.Module):
    """ 2D Image to Patch Embedding
    """
    def __init__(self, img_size, patch_size, in_chans, embed_dim, norm_layer=None):
        super().__init__()
        if (isinstance(img_size, int)):
            img_size = to_2tuple(img_size)
        if (isinstance(patch_size, int)):
            patch_size = to_2tuple(patch_size)
        self.img_size = img_size
        self.patch_size = patch_size
        self.grid_size = (img_size[0] // patch_size[0], img_size[1] // patch_size[1])
        self.num_patches = self.grid_size[0] * self.grid_size[1]

        # 这里的 conv2d是一个不可逆的过程 我们不需要不可逆的过程就直接 32*32维度即可
        self.proj =  nn.Linear(embed_dim, 1024)
        # self.proj = nn.Conv2d(in_chans, embed_dim, kernel_size=patch_size, stride=patch_size)
        self.norm = norm_layer(1024) if norm_layer else nn.Identity()

    def forward(self, x):
        B, C, H, W = x.shape
        assert H == self.img_size[0] and W == self.img_size[1], \
            f"Input image size ({H}*{W}) doesn't match model ({self.img_size[0]}*{self.img_size[1]})."
        # x = self.proj(x)
        # print(x.shape)
        # x =  x.flatten(2).transpose(1, 2)
        x = x.flatten(2)
        x = self.proj(x)
        x = self.norm(x)
        return x

class Attention(nn.Module):
    def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None, attn_drop=0., proj_drop=0.):
        super().__init__()
        self.num_heads = num_heads
        head_dim = dim // num_heads
        self.scale = qk_scale or head_dim ** -0.5

        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)

    def forward(self, x):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]   # make torchscript happy (cannot use tensor as tuple)

        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)

        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        x = self.proj_drop(x)
        return x


def drop_path(x, drop_prob: float = 0., training: bool = False):
    """Drop paths (Stochastic Depth) per sample (when applied in main path of residual blocks).

    This is the same as the DropConnect impl I created for EfficientNet, etc networks, however,
    the original name is misleading as 'Drop Connect' is a different form of dropout in a separate paper...
    See discussion: https://github.com/tensorflow/tpu/issues/494#issuecomment-532968956 ... I've opted for
    changing the layer and argument names to 'drop path' rather than mix DropConnect as a layer name and use
    'survival rate' as the argument.

    """
    if drop_prob == 0. or not training:
        return x
    keep_prob = 1 - drop_prob
    shape = (x.shape[0],) + (1,) * (x.ndim - 1)  # work with diff dim tensors, not just 2D ConvNets
    random_tensor = keep_prob + torch.rand(shape, dtype=x.dtype, device=x.device)
    random_tensor.floor_()  # binarize
    output = x.div(keep_prob) * random_tensor
    return output


class DropPath(nn.Module):
    """Drop paths (Stochastic Depth) per sample  (when applied in main path of residual blocks).
    """
    def __init__(self, drop_prob=None):
        super(DropPath, self).__init__()
        self.drop_prob = drop_prob

    def forward(self, x):
        return drop_path(x, self.drop_prob, self.training)


class Mlp(nn.Module):
    """ MLP as used in Vision Transformer, MLP-Mixer and related networks
    """

    def __init__(self, in_features, hidden_features=None, out_features=None, act_layer=nn.GELU, drop=0.):
        super().__init__()
        out_features = out_features or in_features
        hidden_features = hidden_features or in_features
        self.fc1 = nn.Linear(in_features, hidden_features)
        self.act = act_layer()
        self.fc2 = nn.Linear(hidden_features, out_features)
        self.drop = nn.Dropout(drop)

    def forward(self, x):
        x = self.fc1(x)
        x = self.act(x)
        x = self.drop(x)
        x = self.fc2(x)
        x = self.drop(x)
        return x

class Block(nn.Module):

    def __init__(self, dim, num_heads, mlp_ratio=4., qkv_bias=False, qk_scale=None, drop=0., attn_drop=0.,
                 drop_path=0., act_layer=nn.GELU, norm_layer=nn.LayerNorm):
        super().__init__()
        self.norm1 = norm_layer(dim)
        self.attn = Attention(
            dim, num_heads=num_heads, qkv_bias=qkv_bias, qk_scale=qk_scale, attn_drop=attn_drop, proj_drop=drop)
        # NOTE: drop path for stochastic depth, we shall see if this is better than dropout here
        self.drop_path = DropPath(drop_path) if drop_path > 0. else nn.Identity()
        self.norm2 = norm_layer(dim)
        mlp_hidden_dim = int(dim * mlp_ratio)
        self.mlp = Mlp(in_features=dim, hidden_features=mlp_hidden_dim, act_layer=act_layer, drop=drop)

    def forward(self, x):
        x = x + self.drop_path(self.attn(self.norm1(x)))
        x = x + self.drop_path(self.mlp(self.norm2(x)))
        return x

class MLA(nn.Module):
    def __init__(self,w:int,  h:int,   patch_size,  depth ,  emb_dim , drop_rate = 0.1):
        super(MLA, self).__init__()
        self.W = w
        self.H = h

        # self.cSE = nn.Sequential(
        #     nn.AdaptiveAvgPool2d(1),
        #     nn.Conv2d(4, 4, 1),
        #     nn.ReLU(inplace=True),
        #     nn.Sigmoid(),
        # )
        # self.sSE = nn.Sequential(nn.Conv2d(4, 1, 1), nn.Sigmoid())

        self.PatchSize = patch_size
        self.SoftMax = nn.Softmax(dim = 1)

        norm_layer = nn.LayerNorm
        act_layer = nn.GELU

        self.patchembed_x1  = PatchEmbed( img_size=self.PatchSize, patch_size=self.PatchSize, in_chans=1, embed_dim=emb_dim)
        self.patchembed_x2  = PatchEmbed( img_size=self.PatchSize, patch_size=self.PatchSize, in_chans=1, embed_dim=emb_dim)
        self.patchembed_x3  = PatchEmbed( img_size=self.PatchSize, patch_size=self.PatchSize, in_chans=1, embed_dim=emb_dim)
        # self.patchembed_x4  = PatchEmbed( img_size=self.PatchSize, patch_size=self.PatchSize, in_chans=1, embed_dim=emb_dim)


        # 此处设定path注意力
        dpr = [x.item() for x in torch.linspace(0., 0., depth)]  # stochastic depth decay rule
        self.blocks = nn.Sequential(*[
            Block(
                dim=1024, num_heads=8, mlp_ratio=4., qkv_bias=False, qk_scale=None,
                drop=drop_rate, attn_drop=drop_rate, drop_path=dpr[i], norm_layer=norm_layer, act_layer=act_layer)
            for i in range(depth)])
        self.norm = norm_layer(1024)

        self.apply(_init_vit_weights)


    def forward(self,x):
        # Step 将4个张量维度对齐
        list = []
        for skip in x:
            # 在channel维度做平均
            skip = F.interpolate(skip,size=(self.W,self.H),mode= "bilinear",align_corners= True)
            list.append(   torch.unsqueeze( torch.mean(skip,dim= 1) ,dim= 1)    )

        list[0] = self.patchembed_x1(list[0])
        list[1] = self.patchembed_x2(list[1])
        list[2] = self.patchembed_x3(list[2])
        # list[3] = self.patchembed_x4(list[3])
        # print(list[0].shape)

        # 将 B * 1 *32 * 32的4个图 变成一整张图

        test = torch.cat(list,dim= 1)

        # print(test.shape)  # torch.Size([2, 4, 1024])
        test = self.blocks(test)
        # print(test.shape)
        test = self.norm(test)
        # 每一层做一下softmax
        test = self.SoftMax(test)

        # 将test中  每个维度都还原为 32 * 32
        B,C,_ = test.shape
        test = test.reshape(shape = [B,C,32,32])

        # new_x4 = F.interpolate(input=torch.unsqueeze(test[:, 3, :, :], dim=1), size=(x[3].shape)[2:4],mode= "bilinear",align_corners= True)
        new_x3 = F.interpolate(input=torch.unsqueeze(test[:, 2, :, :], dim=1), size=(x[2].shape)[2:4],mode= "bilinear",align_corners= True)
        new_x2 = F.interpolate(input=torch.unsqueeze(test[:, 1, :, :], dim=1), size=(x[1].shape)[2:4],mode= "bilinear",align_corners= True)
        new_x1 = F.interpolate(input=torch.unsqueeze(test[:, 0, :, :], dim=1), size=(x[0].shape)[2:4],mode= "bilinear",align_corners= True)
        # print(new_x1.shape)
        # print(new_x2.shape)
        # print(new_x4.shape)
        # print(new_x4.min())
        # print(new_x4.max())
        return [ x[0] * new_x1 , x[1] * new_x2 , x[2]*new_x3 ]


    def _init_weights(self, m):
        # this fn left here for compat with downstream users
        _init_vit_weights(m)



class UNet(nn.Module):
    def __init__(self, n_channels, n_classes, bilinear=True,transformer_drop_rate = 0.1):
        super(UNet, self).__init__()
        self.n_channels = n_channels
        self.n_classes = n_classes
        self.bilinear = bilinear

        self.inc = DoubleConv(n_channels, 32)
        self.down1 = Down(32, 64)
        self.down2 = Down(64, 128)
        self.down3 = Down(128, 256)
        factor = 2 if bilinear else 1
        self.down4 = Down(256, 512 // factor)
        self.up1 = Up(512, 256 // factor, bilinear)
        self.up2 = Up(256, 128 // factor, bilinear)
        self.up3 = Up(128, 64 // factor, bilinear)
        self.up4 = Up(64, 32, bilinear)
        self.outc = OutConv(32, n_classes)
        self.mla = MLA(74,74,(74,74),depth=  1,emb_dim= 74*74,drop_rate= transformer_drop_rate)
        # self.mla = MLA(126, 126, 126, 1, emb_dim=126 * 126, drop_rate=transformer_drop_rate)

    def forward(self, x):
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)

        # print(x4.shape)
        # print(x1.shape)
        # print(x1.shape,x2.shape,x3.shape,x4.shape)
        # 加入 MLA模块
        [x1,x2,x3] = self.mla([x1,x2,x3])
        # print(x1.shape,x2.shape,x3.shape,x4.shape)
        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        logits = self.outc(x)
        return logits


## 2.

import torch
import math
import warnings

from torch.nn.init import _calculate_fan_in_and_fan_out


def _no_grad_trunc_normal_(tensor, mean, std, a, b):
    # Cut & paste from PyTorch official master until it's in a few official releases - RW
    # Method based on https://people.sc.fsu.edu/~jburkardt/presentations/truncated_normal.pdf
    def norm_cdf(x):
        # Computes standard normal cumulative distribution function
        return (1. + math.erf(x / math.sqrt(2.))) / 2.

    if (mean < a - 2 * std) or (mean > b + 2 * std):
        warnings.warn("mean is more than 2 std from [a, b] in nn.init.trunc_normal_. "
                      "The distribution of values may be incorrect.",
                      stacklevel=2)

    with torch.no_grad():
        # Values are generated by using a truncated uniform distribution and
        # then using the inverse CDF for the normal distribution.
        # Get upper and lower cdf values
        l = norm_cdf((a - mean) / std)
        u = norm_cdf((b - mean) / std)

        # Uniformly fill tensor with values from [l, u], then translate to
        # [2l-1, 2u-1].
        tensor.uniform_(2 * l - 1, 2 * u - 1)

        # Use inverse cdf transform for normal distribution to get truncated
        # standard normal        tensor.erfinv_()

        # Transform to proper mean, std
        tensor.mul_(std * math.sqrt(2.))
        tensor.add_(mean)

        # Clamp to ensure it's in the proper range
        tensor.clamp_(min=a, max=b)
        return tensor


def trunc_normal_(tensor, mean=0., std=1., a=-2., b=2.):
    # type: (Tensor, float, float, float, float) -> Tensor
    r"""Fills the input Tensor with values drawn from a truncated
    normal distribution. The values are effectively drawn from the
    normal distribution :math:`\mathcal{N}(\text{mean}, \text{std}^2)`
    with values outside :math:`[a, b]` redrawn until they are within
    the bounds. The method used for generating the random values works
    best when :math:`a \leq \text{mean} \leq b`.
    Args:
        tensor: an n-dimensional `torch.Tensor`
        mean: the mean of the normal distribution
        std: the standard deviation of the normal distribution
        a: the minimum cutoff value
        b: the maximum cutoff value
    Examples:
        # >>> w = torch.empty(3, 5)
        # >>> nn.init.trunc_normal_(w)
    """
    return _no_grad_trunc_normal_(tensor, mean, std, a, b)


def variance_scaling_(tensor, scale=1.0, mode='fan_in', distribution='normal'):
    fan_in, fan_out = _calculate_fan_in_and_fan_out(tensor)
    if mode == 'fan_in':
        denom = fan_in
    elif mode == 'fan_out':
        denom = fan_out
    elif mode == 'fan_avg':
        denom = (fan_in + fan_out) / 2

    variance = scale / denom

    if distribution == "truncated_normal":
        # constant is stddev of standard normal truncated to (-2, 2)
        trunc_normal_(tensor, std=math.sqrt(variance) / .87962566103423978)
    elif distribution == "normal":
        tensor.normal_(std=math.sqrt(variance))
    elif distribution == "uniform":
        bound = math.sqrt(3 * variance)
        tensor.uniform_(-bound, bound)
    else:
        raise ValueError(f"invalid distribution {distribution}")


def lecun_normal_(tensor):
    variance_scaling_(tensor, mode='fan_in', distribution='truncated_normal')

def _init_vit_weights(m, n: str = '', head_bias: float = 0., jax_impl: bool = False):
    """ ViT weight initialization
    * When called without n, head_bias, jax_impl args it will behave exactly the same
      as my original init for compatibility with prev hparam / downstream use cases (ie DeiT).
    * When called w/ valid n (module name) and jax_impl=True, will (hopefully) match JAX impl
    """
    if isinstance(m, nn.Linear):
        if n.startswith('head'):
            nn.init.zeros_(m.weight)
            nn.init.constant_(m.bias, head_bias)
        elif n.startswith('pre_logits'):
            lecun_normal_(m.weight)
            nn.init.zeros_(m.bias)
        else:
            if jax_impl:
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    if 'mlp' in n:
                        nn.init.normal_(m.bias, std=1e-6)
                    else:
                        nn.init.zeros_(m.bias)
            else:
                trunc_normal_(m.weight, std=.02)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
    elif jax_impl and isinstance(m, nn.Conv2d):
        # NOTE conv was left to pytorch default in my original init
        lecun_normal_(m.weight)
        if m.bias is not None:
            nn.init.zeros_(m.bias)
    elif isinstance(m, nn.LayerNorm):
        nn.init.zeros_(m.bias)
        nn.init.ones_(m.weight)



if __name__ == '__main__':
    # 用于测试
    model = UNet(1,1)
    model = model.eval()

    # summary(model.cuda(),input_size=(1,256,256),batch_size= 1)
    input_data = torch.randn(size=[2,1,592,592])
    output  = model(input_data)
    torch.save({
        'state_dict': model.state_dict(),
    }, 'model.pth')
    print(output.shape)



