import numpy as np
import torch
from typing import *

from src.enums import *


class Transformer:
    def __init__(self, purpose: str, transforms: list):
        self.purpose = purpose

        self.transforms = transforms
        self.rng = np.random.RandomState(seed=1)

        self.deterministic = False
        if self.purpose == "test":
            self.deterministic = True

    def __call__(self, data: Dict[ChannelEnum, torch.Tensor]) -> Dict[ChannelEnum, torch.Tensor]:
        transformed_data = data

        for transform_config in self.transforms:
            transform_type = TransformEnum(transform_config["type"])

            transform_fct = getattr(self, transform_type.value)
            transformed_data = transform_fct(transform_config, transformed_data)

        return transformed_data

    def white_noise(self, transform_config: dict,
                    data: Dict[ChannelEnum, torch.Tensor]) -> Dict[ChannelEnum, torch.Tensor]:
        stdev = transform_config["stdev"]

        noise = None
        for channel, value in data.items():
            if channel.value in transform_config["apply_to"]:
                if noise is None:
                    if self.deterministic:
                        noise_value = self.rng.normal(loc=0, scale=stdev, size=tuple(value.size()))
                    else:
                        noise_value = np.random.normal(loc=0, scale=stdev, size=tuple(value.size()))
                    noise = value.new_tensor(noise_value, dtype=value.dtype)

                transformed_value = value + noise

                data[channel] = transformed_value

        return data

    def range_adjusted_white_noise(self, transform_config: dict,
                                   data: Dict[ChannelEnum, torch.Tensor]) -> Dict[ChannelEnum, torch.Tensor]:
        params = data[ChannelEnum.PARAMS]
        terrain_resolution = params[0].item()
        robot_position_x = params[1].item()
        robot_position_y = params[2].item()

        sample_grid = data[ChannelEnum.OCCLUDED_ELEVATION_MAP]

        # distance of every pixel from the robot
        lin_x = np.arange(start=-sample_grid.shape[0] / 2, stop=sample_grid.shape[0] / 2, step=1) * terrain_resolution
        lin_y = np.arange(start=-sample_grid.shape[1] / 2, stop=sample_grid.shape[1] / 2, step=1) * terrain_resolution
        off_x, off_y = np.meshgrid(lin_x, lin_y)

        dist_x = robot_position_x - off_x
        dist_y = robot_position_y - off_y
        dist_p2_norm = np.sqrt(np.square(dist_x) + np.square(dist_y))

        stdev = transform_config["stdev"]
        range = transform_config["range"]

        scale = stdev * np.square(1 / range * dist_p2_norm)

        noise = None
        for channel, value in data.items():
            if channel.value in transform_config["apply_to"]:
                if noise is None:
                    if self.deterministic:
                        noise_value = self.rng.normal(loc=0, scale=scale, size=tuple(value.size()))
                    else:
                        noise_value = np.random.normal(loc=0, scale=scale, size=tuple(value.size()))
                    noise = value.new_tensor(noise_value, dtype=value.dtype)

                transformed_value = value + noise

                data[channel] = transformed_value

        return data

    def random_vertical_scale(self, transform_config: dict,
                              data: Dict[ChannelEnum, torch.Tensor]) -> Dict[ChannelEnum, torch.Tensor]:
        min, max = transform_config["min"], transform_config["max"]

        if self.deterministic:
            scale = self.rng.uniform(low=min, high=max)
        else:
            scale = np.random.uniform(low=min, high=max)

        for channel, value in data.items():
            if channel.value in transform_config["apply_to"]:
                if channel is ChannelEnum.PARAMS:
                    transformed_value = value.clone()
                    transformed_value[3] = scale * transformed_value[3]
                else:
                    transformed_value = scale * value

                data[channel] = transformed_value

        return data

    def random_vertical_offset(self, transform_config: dict,
                               data: Dict[ChannelEnum, torch.Tensor]) -> Dict[ChannelEnum, torch.Tensor]:
        min, max = transform_config["min"], transform_config["max"]

        if self.deterministic:
            offset = self.rng.uniform(low=min, high=max)
        else:
            offset = np.random.uniform(low=min, high=max)

        for channel, value in data.items():
            if channel.value in transform_config["apply_to"]:
                if channel is ChannelEnum.PARAMS:
                    transformed_value = value.clone()
                    transformed_value[3] = offset + transformed_value[3]
                else:
                    transformed_value = offset + value

                data[channel] = transformed_value

        return data

    def random_occlusion(self, transform_config: dict,
                         data: Dict[ChannelEnum, torch.Tensor]) -> Dict[ChannelEnum, torch.Tensor]:
        probability = transform_config["probability"]

        occlusion = None
        for channel, value in data.items():
            if channel.value in transform_config["apply_to"]:
                if occlusion is None:
                    if self.deterministic:
                        occlusion = self.rng.choice([0, 1], p=[1 - probability, probability], size=tuple(value.size()))
                    else:
                        occlusion = np.random.choice([0, 1], p=[1 - probability, probability], size=tuple(value.size()))
                    occlusion = torch.tensor(occlusion)

                if channel == ChannelEnum.BINARY_OCCLUSION_MAP:
                    # assert value.dtype == torch.bool
                    #
                    # transformed_value = value.to(dtype=torch.int) + occlusion
                    #
                    # transformed_value[transformed_value > 1] = 1
                    #
                    # data[channel] = transformed_value.to(dtype=torch.bool)

                    value[occlusion == 1] = True
                elif channel == ChannelEnum.OCCLUDED_ELEVATION_MAP:
                    value[occlusion == 1] = np.nan
                else:
                    raise NotImplementedError

                data[channel] = value

        return data
