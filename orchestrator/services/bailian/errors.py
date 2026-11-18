class IntegrationError(ValueError):
    def __init__(self,code,*,uncertain=False,request_id=None):
        self.code=code;self.uncertain=uncertain;self.request_id=request_id
        super().__init__(code)

class Cancelled(IntegrationError):
    def __init__(self):super().__init__('CANCELLED',uncertain=True)
