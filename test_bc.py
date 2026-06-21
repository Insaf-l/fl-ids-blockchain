from web3 import Web3

w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
print("Connecte :", w3.is_connected())
print("Comptes  :", w3.eth.accounts[:3])
