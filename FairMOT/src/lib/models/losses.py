# ------------------------------------------------------------------------------
# Portions of this code are from
# CornerNet (https://github.com/princeton-vl/CornerNet)
# Copyright (c) 2018, University of Michigan
# Licensed under the BSD 3-Clause License
# ------------------------------------------------------------------------------
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import torch
import torch.nn as nn
from .utils import _tranpose_and_gather_feat
import torch.nn.functional as F
import random
import math
import numpy as np

from utils.image import gaussian_radius

def wh_decode(wh_tensor, ratio=4):
    wh_numpy = wh_tensor.cpu().numpy()
    wh_numpy_decode = np.rint(ratio*wh_numpy)
    return wh_numpy_decode[0], wh_numpy_decode[1]

def _slow_neg_loss(pred, gt):
  '''focal loss from CornerNet'''
  pos_inds = gt.eq(1)
  neg_inds = gt.lt(1)

  neg_weights = torch.pow(1 - gt[neg_inds], 4)

  loss = 0
  pos_pred = pred[pos_inds]
  neg_pred = pred[neg_inds]

  pos_loss = torch.log(pos_pred) * torch.pow(1 - pos_pred, 2)
  neg_loss = torch.log(1 - neg_pred) * torch.pow(neg_pred, 2) * neg_weights

  num_pos  = pos_inds.float().sum()
  pos_loss = pos_loss.sum()
  neg_loss = neg_loss.sum()

  if pos_pred.nelement() == 0:
    loss = loss - neg_loss
  else:
    loss = loss - (pos_loss + neg_loss) / num_pos
  return loss


def _neg_loss(pred, gt):
  ''' Modified focal loss. Exactly the same as CornerNet.
      Runs faster and costs a little bit more memory
    Arguments:
      pred (batch x c x h x w)
      gt_regr (batch x c x h x w)
  '''
  pos_inds = gt.eq(1).float()
  neg_inds = gt.lt(1).float()

  neg_weights = torch.pow(1 - gt, 4)

  loss = 0

  pos_loss = torch.log(pred) * torch.pow(1 - pred, 2) * pos_inds
  neg_loss = torch.log(1 - pred) * torch.pow(pred, 2) * neg_weights * neg_inds

  num_pos  = pos_inds.float().sum()
  pos_loss = pos_loss.sum()
  neg_loss = neg_loss.sum()

  if num_pos == 0:
    loss = loss - neg_loss
  else:
    loss = loss - (pos_loss + neg_loss) / num_pos
  return loss

def _not_faster_neg_loss(pred, gt):
    pos_inds = gt.eq(1).float()
    neg_inds = gt.lt(1).float()    
    num_pos  = pos_inds.float().sum()
    neg_weights = torch.pow(1 - gt, 4)

    loss = 0
    trans_pred = pred * neg_inds + (1 - pred) * pos_inds
    weight = neg_weights * neg_inds + pos_inds
    all_loss = torch.log(1 - trans_pred) * torch.pow(trans_pred, 2) * weight
    all_loss = all_loss.sum()

    if num_pos > 0:
        all_loss /= num_pos
    loss -=  all_loss
    return loss

def _slow_reg_loss(regr, gt_regr, mask):
    num  = mask.float().sum()
    mask = mask.unsqueeze(2).expand_as(gt_regr)

    regr    = regr[mask]
    gt_regr = gt_regr[mask]
    
    regr_loss = nn.functional.smooth_l1_loss(regr, gt_regr, size_average=False)
    regr_loss = regr_loss / (num + 1e-4)
    return regr_loss

def _reg_loss(regr, gt_regr, mask):
  ''' L1 regression loss
    Arguments:
      regr (batch x max_objects x dim)
      gt_regr (batch x max_objects x dim)
      mask (batch x max_objects)
  '''
  num = mask.float().sum()
  mask = mask.unsqueeze(2).expand_as(gt_regr).float()

  regr = regr * mask
  gt_regr = gt_regr * mask
    
  regr_loss = nn.functional.smooth_l1_loss(regr, gt_regr, size_average=False)
  regr_loss = regr_loss / (num + 1e-4)
  return regr_loss

class FocalLoss(nn.Module):
  '''nn.Module warpper for focal loss'''
  def __init__(self):
    super(FocalLoss, self).__init__()
    self.neg_loss = _neg_loss

  def forward(self, out, target):
    return self.neg_loss(out, target)

class RegLoss(nn.Module):
  '''Regression loss for an output tensor
    Arguments:
      output (batch x dim x h x w)
      mask (batch x max_objects)
      ind (batch x max_objects)
      target (batch x max_objects x dim)
  '''
  def __init__(self):
    super(RegLoss, self).__init__()
  
  def forward(self, output, mask, ind, target):
    pred = _tranpose_and_gather_feat(output, ind)
    loss = _reg_loss(pred, target, mask)
    return loss

class RegL1Loss(nn.Module):
  def __init__(self):
    super(RegL1Loss, self).__init__()
  
  def forward(self, output, mask, ind, target):
    pred = _tranpose_and_gather_feat(output, ind)
    mask = mask.unsqueeze(2).expand_as(pred).float()
    # loss = F.l1_loss(pred * mask, target * mask, reduction='elementwise_mean')
    loss = F.l1_loss(pred * mask, target * mask, size_average=False)
    loss = loss / (mask.sum() + 1e-4)
    return loss

class NormRegL1Loss(nn.Module):
  def __init__(self):
    super(NormRegL1Loss, self).__init__()
  
  def forward(self, output, mask, ind, target):
    pred = _tranpose_and_gather_feat(output, ind)
    mask = mask.unsqueeze(2).expand_as(pred).float()
    # loss = F.l1_loss(pred * mask, target * mask, reduction='elementwise_mean')
    pred = pred / (target + 1e-4)
    target = target * 0 + 1
    loss = F.l1_loss(pred * mask, target * mask, size_average=False)
    loss = loss / (mask.sum() + 1e-4)
    return loss

class RegWeightedL1Loss(nn.Module):
  def __init__(self):
    super(RegWeightedL1Loss, self).__init__()
  
  def forward(self, output, mask, ind, target):
    pred = _tranpose_and_gather_feat(output, ind)
    mask = mask.float()
    # loss = F.l1_loss(pred * mask, target * mask, reduction='elementwise_mean')
    loss = F.l1_loss(pred * mask, target * mask, size_average=False)
    loss = loss / (mask.sum() + 1e-4)
    return loss

class L1Loss(nn.Module):
  def __init__(self):
    super(L1Loss, self).__init__()
  
  def forward(self, output, mask, ind, target):
    pred = _tranpose_and_gather_feat(output, ind)
    mask = mask.unsqueeze(2).expand_as(pred).float()
    loss = F.l1_loss(pred * mask, target * mask, reduction='elementwise_mean')
    return loss

class BinRotLoss(nn.Module):
  def __init__(self):
    super(BinRotLoss, self).__init__()
  
  def forward(self, output, mask, ind, rotbin, rotres):
    pred = _tranpose_and_gather_feat(output, ind)
    loss = compute_rot_loss(pred, rotbin, rotres, mask)
    return loss

def compute_res_loss(output, target):
    return F.smooth_l1_loss(output, target, reduction='elementwise_mean')

# TODO: weight
def compute_bin_loss(output, target, mask):
    mask = mask.expand_as(output)
    output = output * mask.float()
    return F.cross_entropy(output, target, reduction='elementwise_mean')

def compute_rot_loss(output, target_bin, target_res, mask):
    # output: (B, 128, 8) [bin1_cls[0], bin1_cls[1], bin1_sin, bin1_cos, 
    #                 bin2_cls[0], bin2_cls[1], bin2_sin, bin2_cos]
    # target_bin: (B, 128, 2) [bin1_cls, bin2_cls]
    # target_res: (B, 128, 2) [bin1_res, bin2_res]
    # mask: (B, 128, 1)
    # import pdb; pdb.set_trace()
    output = output.view(-1, 8)
    target_bin = target_bin.view(-1, 2)
    target_res = target_res.view(-1, 2)
    mask = mask.view(-1, 1)
    loss_bin1 = compute_bin_loss(output[:, 0:2], target_bin[:, 0], mask)
    loss_bin2 = compute_bin_loss(output[:, 4:6], target_bin[:, 1], mask)
    loss_res = torch.zeros_like(loss_bin1)
    if target_bin[:, 0].nonzero().shape[0] > 0:
        idx1 = target_bin[:, 0].nonzero()[:, 0]
        valid_output1 = torch.index_select(output, 0, idx1.long())
        valid_target_res1 = torch.index_select(target_res, 0, idx1.long())
        loss_sin1 = compute_res_loss(
          valid_output1[:, 2], torch.sin(valid_target_res1[:, 0]))
        loss_cos1 = compute_res_loss(
          valid_output1[:, 3], torch.cos(valid_target_res1[:, 0]))
        loss_res += loss_sin1 + loss_cos1
    if target_bin[:, 1].nonzero().shape[0] > 0:
        idx2 = target_bin[:, 1].nonzero()[:, 0]
        valid_output2 = torch.index_select(output, 0, idx2.long())
        valid_target_res2 = torch.index_select(target_res, 0, idx2.long())
        loss_sin2 = compute_res_loss(
          valid_output2[:, 6], torch.sin(valid_target_res2[:, 1]))
        loss_cos2 = compute_res_loss(
          valid_output2[:, 7], torch.cos(valid_target_res2[:, 1]))
        loss_res += loss_sin2 + loss_cos2
    return loss_bin1 + loss_bin2 + loss_res


class TripletLoss(nn.Module):
    """Triplet loss with hard positive/negative mining.
    Reference:
    Hermans et al. In Defense of the Triplet Loss for Person Re-Identification. arXiv:1703.07737.
    Code imported from https://github.com/Cysu/open-reid/blob/master/reid/loss/triplet.py.
    Args:
        margin (float): margin for triplet.
    """

    def __init__(self, margin=0.3, mutual_flag=False):
        super(TripletLoss, self).__init__()
        self.margin = margin
        self.ranking_loss = nn.MarginRankingLoss(margin=margin)
        self.mutual = mutual_flag

    def forward(self, inputs, targets):
        """
        Args:
            inputs: feature matrix with shape (batch_size, feat_dim)
            targets: ground truth labels with shape (num_classes)
        """
        n = inputs.size(0)
        # inputs = 1. * inputs / (torch.norm(inputs, 2, dim=-1, keepdim=True).expand_as(inputs) + 1e-12)
        # Compute pairwise distance, replace by the official when merged
        dist = torch.pow(inputs, 2).sum(dim=1, keepdim=True).expand(n, n)
        dist = dist + dist.t()
        dist.addmm_(1, -2, inputs, inputs.t())
        dist = dist.clamp(min=1e-12).sqrt()  # for numerical stability
        # For each anchor, find the hardest positive and negative
        mask = targets.expand(n, n).eq(targets.expand(n, n).t())
        dist_ap, dist_an = [], []
        for i in range(n):
            dist_ap.append(dist[i][mask[i]].max().unsqueeze(0))
            dist_an.append(dist[i][mask[i] == 0].min().unsqueeze(0))
        dist_ap = torch.cat(dist_ap)
        dist_an = torch.cat(dist_an)
        # Compute ranking hinge loss
        y = torch.ones_like(dist_an)
        loss = self.ranking_loss(dist_an, dist_ap, y)
        if self.mutual:
            return loss, dist
        return loss

      
class PairLoss(nn.Module):
    """Pairwise loss with only negatives.
    Args:
        distance_func: function used for calculating distance between embeddings
           -    'euclidean'
           -    'cosine'
        margin (float): margin for negative pairs.
        sampling: method of sampling/mining, options:
           -    'random' = random negative
           -    'hardest' = hardest negative
        positives:
           -    False = only negative pairs used
           -    True = negative and positive pairs used
    """

    def __init__(self, distance_func='euclidean', margin=10.0, sampling='hardest', positives=False):
        super(PairLoss, self).__init__()
        self.margin = margin
        self.ranking_loss = nn.HingeEmbeddingLoss(margin=margin, reduction='mean') #reduction='sum'
        self.sampling = sampling
        self.positives = positives
        self.distance_func = distance_func
        self.cos_distance = nn.CosineSimilarity(dim=0)

    def forward(self, output_id, batch, emb_scale):
        """
        Args:
            output_id: embeddings map
            batch: information dataset, ground truth bounding boxes etc.
        """
        
        id_head_all = _tranpose_and_gather_feat(output_id, batch['ind']) # Object center embeddings of the whole batch
        
        # negatives
        neg_distance = []
        # sample negatives per image in the batch (s_ means single, from single image)
        for b in range(id_head_all.shape[0]):
          s_id_head = id_head_all[b] # embeddings for one image in the batch
          s_anchor_embeddings = s_id_head[batch['reg_mask'][b] > 0].contiguous() # remove embeddings without GT location
          s_anchor_embeddings = emb_scale * F.normalize(s_anchor_embeddings) # normalize
          s_n = s_anchor_embeddings.size(0) # number of anchors in this image
          if self.sampling == 'random': # random negatives sampling
            for i in range(s_n): # For each anchor embedding in the image:
                # Select one random other GT object center embedding (a negative)
                N = list(range(0,s_n))
                N.remove(i) # Make sure negative is not the anchor
                m = random.choice(N)
                # Calculate distances between anchor and negative embeddings (Euclidean distance)
                if self.distance_func == 'cosine':
                  neg_distance.append(1-self.cos_distance(s_anchor_embeddings[i], s_anchor_embeddings[m]).unsqueeze(0))
                else: # distance_func == 'euclidean'
                  neg_distance.append(torch.dist(s_anchor_embeddings[i], s_anchor_embeddings[m], p=2).unsqueeze(0))
              
          else: # hardest negatives sampling
            s_neg_distance = float('inf')*torch.ones(s_n, device=s_anchor_embeddings.device) # Set large distance
            for i in range(s_n): # For each anchor embedding in the image:
              N = list(range(0,s_n))
              N.remove(i)
              for k in N: # For all the negatives
              # Calculate distances between anchor and negative embeddings (Euclidean distance)
                if self.distance_func == 'cosine':
                  neg_distance_next = 1-self.cos_distance(s_anchor_embeddings[i], s_anchor_embeddings[k])
                else: # distance_func == 'euclidean'
                  neg_distance_next = torch.dist(s_anchor_embeddings[i], s_anchor_embeddings[k], p=2)
                if neg_distance_next < s_neg_distance[i]: # Store the smallest distance = hardest negative
                  s_neg_distance[i] = neg_distance_next
            neg_distance.append(s_neg_distance)
        neg_distance = torch.cat(neg_distance) # list to tensor
        
        # positives sampling
        if self.positives:
          anchor_embeddings = id_head_all[batch['reg_mask'] > 0].contiguous() # remove embeddings without GT location
          anchor_embeddings = emb_scale * F.normalize(anchor_embeddings) # normalize
          n = anchor_embeddings.size(0) # get total number of anchors
          
          pos_indj = torch.zeros_like(batch['ind'])
          for j in range(batch['reg_mask'].shape[0]):
            pos_ind = []
            for i in range(batch['reg_mask'].shape[1]):
                if batch['reg_mask'][j,i].cpu().numpy():
                    # get x,y
                    emb_w = output_id.shape[3] # width of the embeddings map
                    emb_h = output_id.shape[2] # height of the embeddings map
                    y, x = divmod(batch['ind'][j,i].cpu().numpy(), emb_w) # extract x and y coordinate of anchor
                    # get radius
                    w, h = wh_decode(batch['wh'][j,i])
                    radius = 0.25*gaussian_radius((math.ceil(h), math.ceil(w)))
                    radius = max(0, int(radius))
                    # shift x,y with fraction of the radius
                    rad_frac = 0.5 # fraction radius distance from centerpoint
                    rnd = np.random.randint(2, size=2) # random left, right, up or down
                    if rnd[0]:
                      pos_x = x
                      if rnd[1]:
                        pos_y = min(emb_h-1, y + math.floor(rad_frac*radius))
                      else:
                        pos_y = max(0, y - math.floor(rad_frac*radius))
                    else:
                      pos_y = y
                      if rnd[1]:
                        pos_x = min(emb_w-1, x + math.floor(rad_frac*radius))
                      else:
                        pos_x = max(0, x - math.floor(rad_frac*radius))
                    # transform that to (batch['ind'] >) single number format
                    pos_ind.append(pos_y * emb_w + pos_x)
            pos_ind_t = torch.Tensor(pos_ind)
            pos_indj[j,:len(pos_ind_t)] = pos_ind_t

          # extract embedding from output feature map
          pos_embeddings = _tranpose_and_gather_feat(output_id, pos_indj)
          pos_embeddings = pos_embeddings[batch['reg_mask'] > 0].contiguous()
          pos_embeddings = emb_scale * F.normalize(pos_embeddings)

          if len(pos_embeddings) == n:
              pos_distance = []
              for i in range(n): # For each anchor embedding in the image:
                  # Calculate distances between anchor and positive embeddings (Euclidean distance)
                  if self.distance_func == 'cosine':
                    pos_distance.append(1-self.cos_distance(anchor_embeddings[i], pos_embeddings[i]).unsqueeze(0))
                  else: # distance_func == 'euclidean'
                    pos_distance.append(torch.dist(anchor_embeddings[i], pos_embeddings[i], p=2).unsqueeze(0))
              pos_distance = torch.cat(pos_distance) # list to tensor
                    
          else:
              print('not same length')
      
          distance = torch.cat((neg_distance,pos_distance)) # concatenate negative and positive distance
          
          neg_y = -1*torch.ones_like(neg_distance) # Make tensor of -ones > negative pairs (different objects)
          pos_y = torch.ones_like(pos_distance) # Make tensor of ones > positive pair
          y = torch.cat((neg_y,pos_y)) # concatenate negative and positive y label

        else: # no positives, only negatives
          # print('only negative')
          distance = neg_distance
          y = -1*torch.ones_like(neg_distance)

        # Calculate pairwise loss > using HingeEmbeddingLoss from PyTorch
        loss = self.ranking_loss(distance, y)
        
        return loss