cd src
python train.py mot --exp_id pairloss_m10_lr4_mot17training_e10 \
--gpus '0' --num_epochs 10 --lr 1e-4 --batch_size 8 --reid_dim 128 \
--arch 'hrnet_18' --load_model '../models/model_45.pth' --freeze backbone \
--train_data "./data/mot17.training" --data_dir '/workspace/datasets/' \
--id_loss 'pairwise' --pairwise_margin 10.0 --pairwise_sampling 'hardest' --positives_sampling True
cd ..