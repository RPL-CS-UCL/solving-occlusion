from collections import deque
import dash
from dash.dependencies import Output, Input
import dash_core_components as dcc
import dash_html_components as html
import h5py
import matplotlib.pyplot as plt
import numpy as np
import pathlib
import plotly
import plotly.graph_objects as go
import random
import torch
from typing import *

from src.enums import *
from src.utils.log import get_logger

logger = get_logger("live_inference_plotter")


def plot_live_inference(results_hdf5_path: pathlib.Path, task_uid: int, purpose: str):
    with h5py.File(str(results_hdf5_path), 'r') as hdf5_file:
        data_hdf5_group_path = f"task_{task_uid}/{purpose}/data"
        comp_dem_dataset = hdf5_file[f"{data_hdf5_group_path}/{ChannelEnum.COMP_DEM.value}"]

        comp_dems = np.array(comp_dem_dataset)

        app = dash.Dash(__name__)
        app.layout = html.Div(
            [
                dcc.Graph(id='live-graph', animate=True),
                dcc.Interval(
                    id='graph-update',
                    interval=1000,
                    n_intervals=0,
                    max_intervals=comp_dem_dataset.shape[0]
                ),
            ]
        )

    @app.callback(
        Output('live-graph', 'figure'),
        [Input('graph-update', 'n_intervals')]
    )
    def update_graph_scatter(i):
        data = plotly.graph_objs.Surface(
                z=comp_dems[i],
                name='Composed DEM'
            )

        return {'data': [data]}

    app.run_server()
