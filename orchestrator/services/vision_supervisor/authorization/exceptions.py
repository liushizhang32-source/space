class AuthorizationError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(status)
