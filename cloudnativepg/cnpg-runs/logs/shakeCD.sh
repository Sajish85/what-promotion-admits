cd /root/cnpg
kubectl patch cluster pg --type merge -p '{"spec":{"failoverDelay":300}}'; sleep 5; python3 bin/harness.py C 10 shake-C-10-r01 | tail -45; python3 bin/harness.py D 10 shake-D-10-r01 | tail -45
