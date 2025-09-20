// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "./LinkTokenMock.sol";

/// @title Mock de Operator de Chainlink para pruebas locales
/// @notice Simula la recepción de requests directrequest y fulfillment
contract OperatorMock {
    LinkTokenMock public linkToken;

    // Mapas para almacenar respuestas
    mapping(bytes32 => uint256) public responsesUint;
    mapping(bytes32 => string) public responsesString;

    event OracleRequest(bytes32 indexed requestId, string data);
    event OracleResponseUint(bytes32 indexed requestId, uint256 result);
    event OracleResponseString(bytes32 indexed requestId, string result);

    constructor(address _link) {
        linkToken = LinkTokenMock(_link);
    }

    /// @notice Simula la función request del Chainlink Operator
    function requestData(bytes32 requestId, string calldata data) external {
        emit OracleRequest(requestId, data);
    }

    /// @notice Simula fulfillment con número (compatibilidad anterior)
    function fulfillRequest(bytes32 requestId, uint256 result) external {
        responsesUint[requestId] = result;
        emit OracleResponseUint(requestId, result);

        // Llamada al consumer que espera uint256
        (bool success, ) = msg.sender.call(
            abi.encodeWithSignature("fulfill(bytes32,uint256)", requestId, result)
        );
        require(success, "Fulfill uint256 failed");
    }

    /// @notice Nuevo: simula fulfillment con string
    function fulfillRequestString(bytes32 requestId, string calldata result) external {
        responsesString[requestId] = result;
        emit OracleResponseString(requestId, result);

        // Llamada al consumer que espera bytes
        (bool success, ) = msg.sender.call(
            abi.encodeWithSignature("fulfill(bytes32,bytes)", requestId, bytes(result))
        );
        require(success, "Fulfill string failed");
    }
}
