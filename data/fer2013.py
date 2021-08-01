import os
import pandas as pd
import torchvision.transforms as transforms
from torch.utils.data import DataLoader
import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset
import cv2
import imgaug.augmenters as iaa


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


class RESCostumDataset(Dataset):
    def __init__(self, category, data, image_size=224, number_of_test=48, transform=True):
        self.category = category
        self.data = data
        self.pixels = self.data['pixels'].tolist()
        self.emotions = pd.get_dummies(self.data['emotion'])

        self.test_number = number_of_test

        self.image_size = (image_size, image_size)
        self.applytransform = transform
        self.transform = transforms.Compose(
            [iaa.Sequential(
                [iaa.Fliplr(p=0.5),
                 iaa.Affine(rotate=(-30, 30))]
            ).augment_image,
             transforms.ToPILImage(),
             transforms.ToTensor()
             ]
        )

    def __len__(self):
        return len(self.pixels)

    def __getitem__(self, idx):
        pixels = self.pixels[idx]
        pixels = list(map(int, pixels.split(" ")))
        image = np.reshape(pixels, (48, 48)).astype(np.uint8)
        image = cv2.resize(image, self.image_size)
        image = np.dstack([image] * 3)
        if self.category == 'test':
            images = [self.transform(image) for i in range(self.test_number)]
            target = self.emotions.iloc[idx].idxmax()
            return images, target
        if self.applytransform:
            image = self.transform(image)
        target = self.emotions.iloc[idx].idxmax()
        return image, target


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


def get_dataloaders(path, bs, num_workers, crop_size, augment, gussian_blur, rotation_range, combine_val_train, cutmix,
                    **kwargs):
    if kwargs['network'] == 'resnet50_cbam':
        if os.path.isdir(path):
            fer2013_train, emotion_mapping_train = load_data(os.path.join(path, 'train.csv'))
            fer2013_val, emotion_mapping_val = load_data(os.path.join(path, 'val.csv'))
            fer2013_test, emotion_mapping_test = load_data(os.path.join(path, 'test.csv'))
            train = RESCostumDataset('train', data=fer2013_train)
            val = RESCostumDataset('val', data=fer2013_val)
            test = RESCostumDataset('test', data=fer2013_test)

        else:
            fer2013, emotion_mapping = load_data(path)
            train = RESCostumDataset('train', data=fer2013[fer2013['Usage'] == 'Training'])
            val = RESCostumDataset('val', data=fer2013[fer2013['Usage'] == 'PublicTest'])
            test = RESCostumDataset('test', data=fer2013[fer2013['Usage'] == 'PrivateTest'])

        trainloader = DataLoader(train, batch_size=bs, shuffle=True, num_workers=num_workers, pin_memory=True)
        valloader = DataLoader(val, batch_size=bs, shuffle=False, num_workers=num_workers, pin_memory=True)
        testloader = DataLoader(test, batch_size=1, shuffle=False, num_workers=num_workers, pin_memory=True)


    else:
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
                transforms.RandomApply([transforms.GaussianBlur(3)], p=0.5 if gussian_blur else 0),
                transforms.Pad(2 if crop_size == 48 else 0),
                transforms.TenCrop(crop_size),
                transforms.Lambda(lambda crops: torch.stack([transforms.ToTensor()(crop) for crop in crops])),
                transforms.Lambda(
                    lambda tensors: torch.stack([transforms.Normalize(mean=(mu,), std=(st,))(t) for t in tensors])),
                transforms.Lambda(
                    lambda tensors: torch.stack(
                        [transforms.RandomErasing(p=0 if cutmix else 0.5)(t) for t in tensors])),
            ])
        else:
            train_transform = test_transform
        if combine_val_train:
            xtrain = np.concatenate([xtrain, xval], axis=0)
            ytrain = np.concatenate([ytrain, yval], axis=0)
            train = CustomDataset(xtrain, ytrain, train_transform)
            test = CustomDataset(xtest, ytest, test_transform)

            trainloader = DataLoader(train, batch_size=bs, shuffle=True, num_workers=num_workers)
            testloader = DataLoader(test, batch_size=bs, shuffle=True, num_workers=num_workers)
            return trainloader, testloader, None
        train = CustomDataset(xtrain, ytrain, train_transform)
        val = CustomDataset(xval, yval, test_transform)
        test = CustomDataset(xtest, ytest, test_transform)

        trainloader = DataLoader(train, batch_size=bs, shuffle=True, num_workers=num_workers)
        valloader = DataLoader(val, batch_size=bs, shuffle=True, num_workers=num_workers)
        testloader = DataLoader(test, batch_size=bs, shuffle=True, num_workers=num_workers)

    return trainloader, valloader, testloader


