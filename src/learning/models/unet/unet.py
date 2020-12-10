""" Full assembly of the parts to form the complete network """

from torch import nn
from typing import *

from .unet_parts import *
from ..base_model import BaseModel
from src.dataloaders.dataloader_meta_info import DataloaderMetaInfo
from src.enums import *
from src.datasets.base_dataset import BaseDataset
from src.learning.loss.loss import total_variation_loss_fct, masked_total_variation_loss_fct


class UNet(BaseModel):
    def __init__(self, hidden_dims: List = None, bilinear=True, **kwargs):
        super(UNet, self).__init__(**kwargs)

        self.bilinear = bilinear
        self.hidden_dims = hidden_dims
        if self.hidden_dims is None:
            self.hidden_dims = [64, 128, 256, 512, 1024]

        factor = 2 if bilinear else 1

        encoder_layers = [DoubleConv(len(self.in_channels), self.hidden_dims[0], dropout_p=self.dropout_p)]
        for in_idx, num_out_channels in enumerate(self.hidden_dims[1:]):
            if (in_idx + 1) >= len(self.hidden_dims[1:]):
                num_down_out_channels = num_out_channels // factor
            else:
                num_down_out_channels = num_out_channels
            encoder_layers.append(Down(self.hidden_dims[in_idx], num_down_out_channels, dropout_p=self.dropout_p))

        self.encoder = nn.Sequential(*encoder_layers)

        decoder_layers = []
        reversed_hidden_dims = self.hidden_dims.copy()
        reversed_hidden_dims.reverse()
        for in_idx, num_out_channels in enumerate(reversed_hidden_dims[1:]):
            if (in_idx + 1) >= len(reversed_hidden_dims[1:]):
                num_up_out_channels = num_out_channels
            else:
                num_up_out_channels = num_out_channels // factor
            decoder_layers.append(Up(reversed_hidden_dims[in_idx], num_up_out_channels,
                                     self.bilinear, dropout_p=self.dropout_p))

        decoder_layers.append(OutConv(reversed_hidden_dims[-1], len(self.out_channels)))

        self.decoder = nn.Sequential(*decoder_layers)

        self.feature_extractor = None

    def forward_pass(self, input: torch.Tensor, data: dict, **kwargs) -> dict:
        encodings = []
        for encoding_idx, encoder_layer in enumerate(self.encoder):
            if len(encodings) == 0:
                encodings.append(encoder_layer(input))
            else:
                encodings.append(encoder_layer(encodings[-1]))

        encodings.reverse()

        x = encodings[0]
        for decoding_idx, decoder_layer in enumerate(self.decoder):
            if decoding_idx + 1 < len(self.decoder):
                x = decoder_layer(x, encodings[decoding_idx+1])
            else:
                x = decoder_layer(x)

        return x.squeeze(dim=1)

    def loss_function(self,
                      loss_config: dict,
                      output: Dict[Union[ChannelEnum, LossEnum, str], torch.Tensor],
                      data: Dict[ChannelEnum, torch.Tensor],
                      dataloader_meta_info: DataloaderMetaInfo = None,
                      **kwargs) -> dict:

        loss_dict = self.eval_loss_function(loss_config=loss_config, output=output, data=data,
                                            dataloader_meta_info=dataloader_meta_info, **kwargs)

        if self.training:
            weights = loss_config.get("train_weights", {})

            reconstruction_weight = weights.get(LossEnum.MSE_REC_ALL.value, 0)
            reconstruction_non_occlusion_weight = weights.get(LossEnum.MSE_REC_NOCC.value, 1)
            reconstruction_occlusion_weight = weights.get(LossEnum.MSE_REC_OCC.value, 1)
            perceptual_weight = weights.get(LossEnum.PERCEPTUAL.value, 0)
            style_weight = weights.get(LossEnum.STYLE.value, 0)
            total_variation_weight = weights.get(LossEnum.TV.value, 0)

            if perceptual_weight > 0 or style_weight > 0:
                artistic_loss = self.artistic_loss_function(loss_config=loss_config, output=output, data=data, **kwargs)
                loss_dict.update(artistic_loss)
            total_variation_loss = masked_total_variation_loss_fct(input=output[ChannelEnum.COMP_DEM],
                                                                   mask=data[ChannelEnum.OCC_MASK])

            loss = reconstruction_weight * loss_dict[LossEnum.MSE_REC_ALL] \
                   + reconstruction_non_occlusion_weight * loss_dict[LossEnum.MSE_REC_NOCC] \
                   + reconstruction_occlusion_weight * loss_dict[LossEnum.MSE_REC_OCC] \
                   + perceptual_weight * loss_dict.get(LossEnum.PERCEPTUAL, 0.) \
                   + style_weight * loss_dict.get(LossEnum.STYLE, 0.) \
                   + total_variation_weight * total_variation_loss

            loss_dict.update({LossEnum.LOSS: loss})

            return loss_dict
        else:
            return loss_dict

    def train(self,  mode: bool = True):
        if mode is True and self.config.get("feature_extractor", False) is True:
            device, = list(set(p.device for p in self.parameters()))
            self.feature_extractor = VGG16FeatureExtractor()
            self.feature_extractor = self.feature_extractor.to(device=device)
        else:
            self.feature_extractor = None

        super().train(mode=mode)
