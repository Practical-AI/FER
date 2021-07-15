import os
import numpy as np
import pandas as pd
import torch
import torchvision.transforms as transforms
from torch.utils.data import DataLoader

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset


class CustomDataset(Dataset):
    def __init__(self, images, labels, transform=None, augment=False):
        self.images = images
        self.labels = labels
        self.transform = transform
        self.augment = augment

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()

        img = np.array(self.images[idx])

        img = Image.fromarray(img)

        if self.transform:
            img = self.transform(img)

        label = torch.tensor(self.labels[idx]).type(torch.long)
        sample = (img, label)

        return sample


def load_data(path='datasets/fer2013/fer2013.csv'):
    fer2013 = pd.read_csv(path)
    emotion_mapping = {0: 'Angry', 1: 'Disgust', 2: 'Fear', 3: 'Happy', 4: 'Sad', 5: 'Surprise', 6: 'Neutral'}

    return fer2013, emotion_mapping


def prepare_data(data):
    """ Prepare data for modeling
        input: data frame with labels und pixel data
        output: image and label array """

    image_array = np.zeros(shape=(len(data), 48, 48))
    image_label = np.array(list(map(int, data['emotion'])))

    for i, row in enumerate(data.index):
        image = np.fromstring(data.loc[row, 'pixels'], dtype=int, sep=' ')
        image = np.reshape(image, (48, 48))
        image_array[i] = image

    return image_array, image_label


def get_dataloaders(path, bs, num_workers, crop_size, augment, gussian_blur, rotation_range):
    """ Prepare train, val, & test dataloaders
        Augment training data using:
            - cropping
            - shifting (vertical/horizental)
            - horizental flipping
            - rotation

        input: path to fer2013 csv file
        output: (Dataloader, Dataloader, Dataloader) """
    if os.path.isdir(path):
        fer2013_train, emotion_mapping_train = load_data(os.path.join(path, 'train.csv'))
        fer2013_val, emotion_mapping_val = load_data(os.path.join(path, 'val.csv'))
        fer2013_test, emotion_mapping_test = load_data(os.path.join(path, 'test.csv'))
        xtrain, ytrain = prepare_data(fer2013_train)
        xval, yval = prepare_data(fer2013_val)
        xtest, ytest = prepare_data(fer2013_test)
    else:
        fer2013, emotion_mapping = load_data(path)
        xtrain, ytrain = prepare_data(fer2013[fer2013['Usage'] == 'Training'])
        xval, yval = prepare_data(fer2013[fer2013['Usage'] == 'PublicTest'])
        xtest, ytest = prepare_data(fer2013[fer2013['Usage'] == 'PrivateTest'])

    mu, st = 0, 255

    test_transform = transforms.Compose([
        transforms.Pad(2 if crop_size == 48 else 0),
        transforms.TenCrop(crop_size),
        transforms.Lambda(lambda crops: torch.stack([transforms.ToTensor()(crop) for crop in crops])),
        transforms.Lambda(
            lambda tensors: torch.stack([transforms.Normalize(mean=(mu,), std=(st,))(t) for t in tensors])),
    ])

    if augment:
        train_transform = transforms.Compose([
            transforms.RandomResizedCrop(48, scale=(0.8, 1.2)),
            transforms.RandomApply([transforms.RandomAffine(0, translate=(0.2, 0.2))], p=0.5),
            transforms.RandomHorizontalFlip(),
            transforms.RandomApply([transforms.RandomRotation(rotation_range)], p=0.5),
            transforms.RandomApply([transforms.GaussianBlur(3)], p=0.5 if gussian_blur else 0) ,
            transforms.Pad(2 if crop_size == 48 else 0),
            transforms.TenCrop(crop_size),
            transforms.Lambda(lambda crops: torch.stack([transforms.ToTensor()(crop) for crop in crops])),
            transforms.Lambda(
                lambda tensors: torch.stack([transforms.Normalize(mean=(mu,), std=(st,))(t) for t in tensors])),
            transforms.Lambda(lambda tensors: torch.stack([transforms.RandomErasing(p=0.5)(t) for t in tensors])),
        ])
    else:
        train_transform = test_transform

    train = CustomDataset(xtrain, ytrain, train_transform)
    val = CustomDataset(xval, yval, test_transform)
    test = CustomDataset(xtest, ytest, test_transform)

    trainloader = DataLoader(train, batch_size=bs, shuffle=True, num_workers=num_workers)
    valloader = DataLoader(val, batch_size=bs, shuffle=True, num_workers=num_workers)
    testloader = DataLoader(test, batch_size=bs, shuffle=True, num_workers=num_workers)

    return trainloader, valloader, testloader
