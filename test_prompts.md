what are the unique values in cluster_labels column?

can you give me all the Pvalb clusters?


## plotting
- sample 20 cells and scatter log_volume vs elongation

## basic annotation
please add a new annotation layer "a1" with a point at the current camera position.

## Add annotation from query
Can you get the top log_volume in each cluster_label. include spatial coordinates. Then make a new annotation layer with a point for each cell. Call the layer "Clusters". Make it Green.


## ctl data
+ https://aind-neuroglancer-sauujisjxq-uw.a.run.app/#!s3://aind-open-data/HCR_785054-v1_2025-10-31_13-00-00/raw_data.json


## sst spot count
In the csv, group_by cell_id and get the Sst cell with highest spot count

f.filter(pl.col('mixed_gene')=='Sst').group_by('cell_id').agg(pl.count('spot_id').alias('spot_count')).sort('spot_count', descending=True).head(1).select([pl.col('cell_id'), pl.col('spot_count')])

## spots for a cell
**prompt**
make a annotation layer "cell_spots"
query the csv for cell_id = 74330 and chan = 638, include spatial cols x y z
add annotation points for each location in query
set viewer camera to the first spot location in the query


## Use case
1) oregano with r4/r5 spots
+ csv: https://neuroglancer-demo.appspot.com/#!s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/fused_ng.json

 
# user cases
+ 1) given coreg what is happening(Qc/validation/)
    1) annotate all coreg cells; view them
    2) Spots for r4 to r5 on oregano round 5. 
    3) bounding box around the coreg volume. 




# next feature (11/3)

yes place it in a viewer controls card in the settings panel, keep open by default. while we are at it we can remove the opened: ng link from the settings panel it is redundant . please create a plan and then implement


## annotations

"layers": [
    {
      "type": "image",
      "source": "zarr://s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/image_tile_fusing/fused/channel_405.zarr",
      "localDimensions": {
        "c'": [
          1,
          ""
        ]
      },
      "localPosition": [
        0
      ],
      "tab": "source",
      "opacity": 1,
      "blend": "additive",
      "shader": "#uicontrol vec3 color color(default=\"#ffffff\")\n#uicontrol invlerp normalized\nvoid main() {\nemitRGB(color * normalized());\n}",
      "shaderControls": {
        "normalized": {
          "range": [
            90,
            1200
          ]
        }
      },
      "name": "CH_405:Rn28s"
    },
    {
      "type": "image",
      "source": "zarr://s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/image_tile_fusing/fused/channel_488.zarr",
      "localDimensions": {
        "c'": [
          1,
          ""
        ]
      },
      "localPosition": [
        0
      ],
      "tab": "source",
      "opacity": 1,
      "blend": "additive",
      "shader": "#uicontrol vec3 color color(default=\"#00ff00\")\n#uicontrol invlerp normalized\nvoid main() {\nemitRGB(color * normalized());\n}",
      "shaderControls": {
        "normalized": {
          "range": [
            90,
            1200
          ]
        }
      },
      "name": "CH_488:Cck"
    },
    {
      "type": "image",
      "source": "zarr://s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/image_tile_fusing/fused/channel_514.zarr",
      "localDimensions": {
        "c'": [
          1,
          ""
        ]
      },
      "localPosition": [
        0
      ],
      "tab": "source",
      "opacity": 1,
      "blend": "additive",
      "shader": "#uicontrol vec3 color color(default=\"#ff0000\")\n#uicontrol invlerp normalized\nvoid main() {\nemitRGB(color * normalized());\n}",
      "shaderControls": {
        "normalized": {
          "range": [
            90,
            1200
          ]
        }
      },
      "name": "CH_514:Npy"
    },
    {
      "type": "image",
      "source": "zarr://s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/image_tile_fusing/fused/channel_561.zarr",
      "localDimensions": {
        "c'": [
          1,
          ""
        ]
      },
      "localPosition": [
        0
      ],
      "tab": "source",
      "opacity": 1,
      "blend": "additive",
      "shader": "#uicontrol vec3 color color(default=\"#0000ff\")\n#uicontrol invlerp normalized\nvoid main() {\nemitRGB(color * normalized());\n}",
      "shaderControls": {
        "normalized": {
          "range": [
            90,
            1200
          ]
        }
      },
      "name": "CH_561:Pvalb"
    },
    {
      "type": "image",
      "source": "zarr://s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/image_tile_fusing/fused/channel_594.zarr",
      "localDimensions": {
        "c'": [
          1,
          ""
        ]
      },
      "localPosition": [
        0
      ],
      "tab": "source",
      "opacity": 1,
      "blend": "additive",
      "shader": "#uicontrol vec3 color color(default=\"#00ffff\")\n#uicontrol invlerp normalized\nvoid main() {\nemitRGB(color * normalized());\n}",
      "shaderControls": {
        "normalized": {
          "range": [
            90,
            1200
          ]
        }
      },
      "name": "CH_594:Sst"
    },
    {
      "type": "image",
      "source": "zarr://s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/image_tile_fusing/fused/channel_638.zarr",
      "localDimensions": {
        "c'": [
          1,
          ""
        ]
      },
      "localPosition": [
        0
      ],
      "tab": "source",
      "opacity": 1,
      "blend": "additive",
      "shader": "#uicontrol vec3 color color(default=\"#ff00ff\")\n#uicontrol invlerp normalized\nvoid main() {\nemitRGB(color * normalized());\n}",
      "shaderControls": {
        "normalized": {
          "range": [
            90,
            1200
          ]
        }
      },
      "name": "CH_638:Vip"
    },
    {
      "type": "annotation",
      "source": {
        "url": "local://annotations",
        "transform": {
          "outputDimensions": {
            "x": [
              2.473600491570986e-7,
              "m"
            ],
            "y": [
              2.473600491570986e-7,
              "m"
            ],
            "z": [
              0.000001,
              "m"
            ],
            "t": [
              0.001,
              "s"
            ]
          }
        }
      },
      "tool": "annotatePoint",
      "tab": "annotations",
      "annotationColor": "#00ff00",
      "annotations": [
        {
          "point": [
            5245.23046875,
            4257.62255859375,
            782.9999389648438,
            0
          ],
          "type": "point",
          "id": "3b3bfb09c4eba4452b749cbe58e7f6dd7a70249e"
        },
        {
          "point": [
            5260.39404296875,
            4250.95068359375,
            782.9999389648438,
            0
          ],
          "type": "point",
          "id": "8549ca60da8cb046f6393571f01a739ef51c7f52"
        },
        {
          "point": [
            5240.98486328125,
            4232.7548828125,
            782.9999389648438,
            0
          ],
          "type": "point",
          "id": "3274cf063ac4119d3e7c65e0af565e32a445ff38"
        },
        {
          "point": [
            5215.5107421875,
            4254.58984375,
            782.9999389648438,
            0
          ],
          "type": "point",
          "id": "4a5dc797b2c4c38b354e54725066c0f1c3b4d407"
        },
        {
          "point": [
            5237.345703125,
            4275.2119140625,
            782.9999389648438,
            0
          ],
          "type": "point",
          "id": "cf3312db8b613d49b35023cb01dd3e01dd66e13a"
        },
        {
          "point": [
            5264.6396484375,
            4268.5400390625,
            782.9999389648438,
            0
          ],
          "type": "point",
          "id": "46ed12721231b919d8ba73be2dabdd5b442fd6ed"
        },
        {
          "point": [
            5280.4091796875,
            4256.40966796875,
            782.9999389648438,
            0
          ],
          "type": "point",
          "id": "cd0c8eb2f463fb465e740f74d0c63431265fd60f"
        }
      ],
      "name": "cell_spots"
    }