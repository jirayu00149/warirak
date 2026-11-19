# Data and model credits

- TACO: Pedro F. Proença and Pedro Simões, TACO: Trash Annotations in Context for Litter Detection (2020), https://github.com/pedropro/TACO , https://doi.org/10.5281/zenodo.3587843 . Annotations CC BY 4.0. Images follow their individual source licences, default CC BY 4.0 where unspecified by the source.
- TACO image mirror: Pictograph, https://huggingface.co/datasets/pictograph/taco . Target annotations were checked against primary TACO annotations; six conflicting cases were excluded.
- SC-FloatWaste: https://huggingface.co/datasets/OliviaWuYJ/sc-floatwaste , CC BY 4.0. Only plastic beverage/other bottle categories were mapped to plastic_bottle; ambiguous DH_lid-containing frames were excluded rather than relabelled as caps.
- Reviewed ExtendedTACO: RoboticsLab URJC, https://huggingface.co/datasets/roboticslaburjc/ExtendedTACO-reviewed . Detection rectangles from darknet-labels/. Annotations CC BY 4.0; individual image licences prevail. Known/held-out visually similar images were excluded before train-only additions.
- Ultralytics YOLO26: https://github.com/ultralytics/ultralytics , AGPL-3.0 / applicable commercial licence. This project uses AGPL-3.0 and provides its source separately.

Image changes: verified dimensions, resized longest edge to at most 1280 preserving aspect ratio, stripped EXIF consistently with the annotation coordinate system, JPEG quality 93. Categories were merged into plastic_bottle and bottle_cap; boxes were clipped at image boundaries. Further augmentation during training is recorded in the training configuration. Source revisions, image checksums and source filenames are in dataset-manifest.json.

The navigation environment, observations and trajectories are synthetic; their simulation results are not field measurements.
