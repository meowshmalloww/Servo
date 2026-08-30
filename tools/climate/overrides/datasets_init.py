"""ClimateNeRF dataset registry restricted to Servo's qualified COLMAP input."""

from datasets.colmap import ColmapDataset


dataset_dict = {"colmap": ColmapDataset}
