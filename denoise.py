import torch 
from config import *
from diffusion import *
import matplotlib.pyplot as plt 
from dataset import tensor_to_pil
from lora import LoraLayer
from torch import nn 
from lora import inject_lora

def backward_denoise(model,batch_x_t,batch_cls):
    steps=[batch_x_t,]

    global alphas,alphas_cumprod,variance

    model=model.to(DEVICE)
    batch_x_t=batch_x_t.to(DEVICE)
    alphas=alphas.to(DEVICE)
    alphas_cumprod=alphas_cumprod.to(DEVICE)
    variance=variance.to(DEVICE)
    batch_cls=batch_cls.to(DEVICE)
    
    # BN层的存在，需要eval模式避免推理时跟随batch的数据分布，但是相反训练的时候需要更加充分让它见到各种batch数据分布
    model.eval()
    with torch.no_grad():
        for t in range(T-1,-1,-1):
            batch_t=torch.full((batch_x_t.size(0),),t).to(DEVICE) #[999,999,....]
            # 预测x_t时刻的噪音
            batch_predict_noise_t=model(batch_x_t,batch_t,batch_cls)
            # 生成t-1时刻的图像
            shape=(batch_x_t.size(0),1,1,1)
            batch_mean_t=1/torch.sqrt(alphas[batch_t].view(*shape))*  \
                (
                    batch_x_t-
                    (1-alphas[batch_t].view(*shape))/torch.sqrt(1-alphas_cumprod[batch_t].view(*shape))*batch_predict_noise_t
                )
            if t!=0:
                batch_x_t=batch_mean_t+ \
                    torch.randn_like(batch_x_t)* \
                    torch.sqrt(variance[batch_t].view(*shape))
            else:
                batch_x_t=batch_mean_t
            batch_x_t=torch.clamp(batch_x_t, -1.0, 1.0).detach()
            steps.append(batch_x_t)
    return steps 

if __name__=='__main__':
    # 加载模型
    model=torch.load('model.pt')

    USE_LORA=True

    if USE_LORA:
        # 向nn.Linear层注入Lora
        for name,layer in model.named_modules():
            name_cols=name.split('.')
            # 过滤出cross attention使用的linear权重
            filter_names=['w_q','w_k','w_v']
            if any(n in name_cols for n in filter_names) and isinstance(layer,nn.Linear):
                inject_lora(model,name,layer)

        # lora权重的加载
        try:
            restore_lora_state=torch.load('lora.pt')
            # for key in restore_lora_state:
            #     if 'w_q' in key and 'lora_b' in key:
            #         print(key, restore_lora_state[key])
            model.load_state_dict(restore_lora_state,strict=False)
        except:
            pass 

        model=model.to(DEVICE)

        # for name,param in model.named_parameters():
        #     if 'lora_b' in name:
        #         print(name,param)

        # lora权重合并到主模型
        for name,layer in model.named_modules():
            name_cols=name.split('.')

            if isinstance(layer,LoraLayer):
                children=name_cols[:-1]
                cur_layer=model 
                for child in children:
                    cur_layer=getattr(cur_layer,child)  
                #print(name,type(layer),layer.lora_b)
                #print(name,layer.lora_b)
                lora_weight=(layer.lora_a@layer.lora_b)*layer.alpha/layer.r
                before_weight=layer.raw_linear.weight.clone()
                layer.raw_linear.weight=nn.Parameter(layer.raw_linear.weight.add(lora_weight.T)).to(DEVICE)    # 把Lora参数加到base model的linear weight上
                setattr(cur_layer,name_cols[-1],layer.raw_linear)
    
    # 打印模型结构
    #print(model)

    # 生成噪音图
    batch_size=10
    batch_x_t=torch.randn(size=(batch_size,1,IMG_SIZE,IMG_SIZE))  # (5,1,48,48)
    batch_cls=torch.arange(start=0,end=10,dtype=torch.long)   # 引导词promot
    # 逐步去噪得到原图
    steps=backward_denoise(model,batch_x_t,batch_cls)
    # 绘制数量
    num_imgs=20
    # 绘制还原过程
    plt.figure(figsize=(15,15))
    for b in range(batch_size):
        for i in range(0,num_imgs):
            idx=int(T/num_imgs)*(i+1)
            # 像素值还原到[0,1]
            final_img=(steps[idx][b].to('cpu')+1)/2
            # tensor转回PIL图
            final_img=tensor_to_pil(final_img)
            plt.subplot(batch_size,num_imgs,b*num_imgs+i+1)
            plt.imshow(final_img)
    plt.show()