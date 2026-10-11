# Person detector

These two files are downloaded onto the machine and are not committed:

| File | Bytes | Source |
|---|---|---|
| `deploy.prototxt` | 44667 | https://github.com/chuanqi305/MobileNet-SSD/blob/master/deploy.prototxt |
| `mobilenet_iter_73000.caffemodel` | 23306119 | https://github.com/chuanqi305/MobileNet-SSD/blob/master/mobilenet_iter_73000.caffemodel |

Direct downloads used:

- https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt
- https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/mobilenet_iter_73000.caffemodel

Project: https://github.com/chuanqi305/MobileNet-SSD

License: MIT. Copyright (c) 2018 chuanqi305. The license text is the repository `LICENSE` file: https://github.com/chuanqi305/MobileNet-SSD/blob/master/LICENSE

The network is MobileNet-SSD trained on PASCAL VOC. OpenCV's DNN module reads it. Class 15 is "person". This note is only about where the files came from. It is not an accuracy measurement.

Set `PERSON_MODEL_DIR` to this directory.
