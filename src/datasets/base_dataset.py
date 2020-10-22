from abc import ABC, abstractmethod
import numpy as np
import pathlib
from PIL import Image
import tifffile
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset as TorchDataset, Subset
from torchvision.datasets.folder import default_loader as torchvision_default_loader
from typing import *

from src.enums.channel_enum import ChannelEnum
from src.utils.log import get_logger

logger = get_logger("base_dataset")


class BaseDataset(ABC):
    def __init__(self, config: dict, dataset_path: pathlib.Path, purpose: str = None,
                 transform: Optional[Callable] = None):
        self.config = config
        self.purpose = purpose
        self.dataset_path = dataset_path

        self.transform = transform

        self.img_loader = torchvision_default_loader

    @staticmethod
    def prepare_keys(data: dict) -> np.array:
        for key, value in data.items():
            if type(key) == str:
                new_key = ChannelEnum(key)
                data[new_key] = value
                del data[key]
        return data

    def prepare_item(self, data: dict) -> Dict[ChannelEnum, torch.Tensor]:
        output = {}
        for key, value in data.items():
            if issubclass(type(value), pathlib.Path):
                if value.suffix in [".tif", ".tiff", ".TIF", ".TIFF"]:
                    value = tifffile.imread(str(value))
                else:
                    value = self.img_loader(str(value))

            if issubclass(type(value), Image.Image):
                value = torch.tensor(np.array(value))
                if value.dim() > 2:
                    value = value[0, ...]
            elif issubclass(type(value), np.ndarray):
                value = torch.tensor(value)

            if key == ChannelEnum.BINARY_OCCLUSION_MAP:
                value = value.to(dtype=torch.bool)

            output[key] = value

        if ChannelEnum.BINARY_OCCLUSION_MAP not in output and ChannelEnum.OCCLUDED_ELEVATION_MAP in output:
            output[ChannelEnum.BINARY_OCCLUSION_MAP] = self.create_binary_occlusion_map(
                occluded_elevation_map=output[ChannelEnum.OCCLUDED_ELEVATION_MAP])

        # we require square dimension for now
        if ChannelEnum.GROUND_TRUTH_ELEVATION_MAP in output:
            sample_map = output[ChannelEnum.GROUND_TRUTH_ELEVATION_MAP]
        elif ChannelEnum.BINARY_OCCLUSION_MAP in output:
            sample_map = output[ChannelEnum.BINARY_OCCLUSION_MAP]
        else:
            raise ValueError

        assert sample_map.size(0) == sample_map.size(1)
        if type(self.config["size"]) == list:
            assert self.config["size"][0] == self.config["size"][1]
        input_size = sample_map.size(0)
        if type(self.config["size"]) == list:
            output_size = self.config["size"][0]
        elif type(self.config["size"]) == int:
            output_size = self.config["size"]
        else:
            raise ValueError

        if input_size != output_size:
            for key, value in output.items():
                if key == ChannelEnum.PARAMS:
                    # we need to apply the resizing to the terrain resolution
                    input_resolution = value[0].item()

                    output_resolution = input_resolution * input_size / output_size
                    value[0] = output_resolution
                else:
                    if value.dtype == torch.bool:
                        value = value.to(dtype=torch.float)

                    interpolation_input = value.unsqueeze(dim=0).unsqueeze(dim=0)
                    interpolation_output = F.interpolate(interpolation_input, size=self.config["size"])
                    value = interpolation_output.squeeze()

                output[key] = value

        if ChannelEnum.BINARY_OCCLUSION_MAP in output and ChannelEnum.GROUND_TRUTH_ELEVATION_MAP in output:
            output[ChannelEnum.BINARY_OCCLUSION_MAP] = output[ChannelEnum.BINARY_OCCLUSION_MAP].to(dtype=torch.bool)
            output[ChannelEnum.OCCLUDED_ELEVATION_MAP] = self.create_occluded_elevation_map(
                elevation_map=output[ChannelEnum.GROUND_TRUTH_ELEVATION_MAP],
                binary_occlusion_map=output[ChannelEnum.BINARY_OCCLUSION_MAP])

        elif ChannelEnum.OCCLUDED_ELEVATION_MAP in output:
            # TODO: we also need to do resizing for occluded elevation maps if we cannot freshly generate them
            pass
        else:
            raise ValueError

        if self.transform is not None:
            output[ChannelEnum.OCCLUDED_ELEVATION_MAP] = self.transform(output[ChannelEnum.OCCLUDED_ELEVATION_MAP])

        return output

    def create_occluded_elevation_map(self, elevation_map: torch.Tensor,
                                      binary_occlusion_map: torch.Tensor) -> torch.Tensor:
        occluded_elevation_map = elevation_map.clone()

        occluded_elevation_map[binary_occlusion_map == 1] = np.nan

        return occluded_elevation_map

    def create_binary_occlusion_map(self, occluded_elevation_map: torch.Tensor) -> torch.Tensor:
        binary_occlusion_map = (occluded_elevation_map != occluded_elevation_map)

        return binary_occlusion_map
