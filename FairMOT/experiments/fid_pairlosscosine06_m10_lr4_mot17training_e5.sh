cd src
python train.py mot --exp_id fid_pairlosscosine06_m10_lr4_mot17training_e50 \
--gpus '2' --num_epochs 5 --lr 1e-4  --batch_size 8 --reid_dim 128 \
--arch 'hrnet_18' --load_model '../models/model_45.pth' --freeze backbone_det \
--train_data "./data/mot17.training" --data_dir '/workspace/datasets/' \
--id_loss 'pairwise' --pairwise_margin 0.6 --pairwise_sampling 'hardest' --positives_sampling True \
--distance_func 'cosine'
cd ..