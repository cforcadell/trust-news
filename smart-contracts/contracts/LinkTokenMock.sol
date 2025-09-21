// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title Mock de LINK token para pruebas en local
/// @notice Simula el contrato oficial de LINK en testnets
contract LinkTokenMock is ERC20 {
    constructor(uint256 initialSupply) ERC20("Chainlink Token", "LINK") {
        _mint(msg.sender, initialSupply);
    }

    /// @notice Compatibilidad con el método transferAndCall usado por Chainlink
    function transferAndCall(
        address to,
        uint256 value,
        bytes calldata data
    ) external returns (bool success) {
        _transfer(msg.sender, to, value);
        // Si el contrato receptor necesita lógica, debería implementarse aquí.
        // Para pruebas locales dejamos el método simple.
        emit Transfer(msg.sender, to, value);
        return true;
    }
}
