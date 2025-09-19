// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./LinkTokenMock.sol";

/// @title Mock de Operator de Chainlink para pruebas locales
/// @notice Simula la recepción de requests directrequest y fulfillment
contract OperatorMock {
    LinkTokenMock public linkToken;

    // Map para almacenar respuestas de jobs
    mapping(bytes32 => uint256) public responses;

    event OracleRequest(bytes32 indexed requestId, string data);
    event OracleResponse(bytes32 indexed requestId, uint256 result);

    constructor(address _link) {
        linkToken = LinkTokenMock(_link);
    }

    /// @notice Simula la función request del Chainlink Operator
    function requestData(bytes32 requestId, string calldata data) external {
        emit OracleRequest(requestId, data);
        // Para el mock no hacemos nada, solo emitimos evento
    }

    /// @notice Función que simula que el nodo Chainlink envía la respuesta
    function fulfillRequest(bytes32 requestId, uint256 result) external {
        responses[requestId] = result;
        emit OracleResponse(requestId, result);
    }
}
